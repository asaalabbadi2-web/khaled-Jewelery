"""POS claim router — POST /api/v1/items/{item_id}/pos-claim.

Terminal fix for INV-4 (ADR-016 §H1): replaces the ERP's pre-transaction HTTP
availability check with an in-Commerce-transaction atomic claim. The ERP no
longer reads reservation state before writing — it requests a claim from
Commerce, which holds the row lock for the duration of the POS sale.

Design inversion (ADR-016 §N1):
    Before: ERP reads availability, then writes an invoice.
    After:  ERP requests a claim (POS becomes the requester, not the reader).
            Commerce grants or denies atomically. ERP writes only after a grant.

The three-step ERP integration is:
    1. POST /items/{id}/pos-claim       — request exclusive intent
    2. (ERP opens its own DB transaction and writes the invoice)
    3. POST /items/{id}/pos-claim/{claim_id}/confirm   — sale committed
       OR DELETE /items/{id}/pos-claim/{claim_id}      — sale rolled back

Auth: X-POS-Secret header, verified via require_pos_auth (machine-to-machine).

Concurrency — two-layer defence:
    Layer 1: SELECT FOR UPDATE on ALL ACTIVE PosClaimRows for the item (including
    expired ones) serialises the sweep+insert pair across concurrent requests.
    If an unexpired ACTIVE row is found, we deny immediately.  If only expired
    ACTIVE rows are found, we transition them to EXPIRED and insert the new claim
    — all within the same transaction under the row lock.

    Layer 2: Partial unique index `ix_pos_claims_one_active_per_item`
    (UNIQUE(item_id) WHERE status='ACTIVE') catches the residual INSERT race
    for the fresh-item case where no prior ACTIVE row exists (so Layer 1 locked
    nothing).  The IntegrityError is caught and translated to a clean 409 so the
    POS terminal receives the same structured rejection it would get from Layer 1.

    SQLite note: SELECT FOR UPDATE is a no-op in SQLite (tests); Layer 2 remains
    effective because SQLite serialises writers and the partial index is enforced.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_serializer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from yasargold_commerce.auth import require_pos_auth
from yasargold_commerce.db import get_db
from yasargold_commerce.infra.pos_claim_orm import PosClaimRow
from yasargold_commerce.infra.reservation_orm import ReservationRow

router = APIRouter(prefix="/api/v1", tags=["pos-claims"])
log = logging.getLogger(__name__)

_DEFAULT_TTL_SECONDS = 30


def _normalize_to_utc(dt: datetime) -> datetime:
    """Normalise a potentially offset-naive datetime (SQLite) to UTC-aware."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PosClaimRequest(BaseModel):
    ttl_seconds: int = _DEFAULT_TTL_SECONDS


class PosClaimResponse(BaseModel):
    claim_id:   str
    item_id:    int
    expires_at: datetime

    @field_serializer("expires_at")
    def _serialize_dt(self, v: datetime) -> str:
        return v.isoformat()


class PosClaimStatusResponse(BaseModel):
    claim_id: str
    status:   str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/items/{item_id}/pos-claim",
    status_code=201,
    response_model=PosClaimResponse,
    summary="Request an exclusive POS claim for an item",
)
def create_pos_claim(
    item_id: int,
    body:    PosClaimRequest = PosClaimRequest(),
    db:      Session = Depends(get_db),
    _:       None    = Depends(require_pos_auth),
) -> PosClaimResponse:
    """Atomically check reservation state and create a POS claim.

    Returns:
        201 — claim granted; ERP may now write its invoice
        409 — item is online-reserved or already claimed by another POS request
        401/503 — auth failure
    """
    now = datetime.now(timezone.utc)

    # Check for an ACTIVE online reservation.  SELECT FOR UPDATE serialises
    # concurrent requests that race on the same item with an existing reservation
    # (PostgreSQL); silently a no-op on SQLite in tests.
    existing_reservation = db.execute(
        select(ReservationRow)
        .where(
            ReservationRow.item_id == item_id,
            ReservationRow.status  == "ACTIVE",
            ReservationRow.valid_until > now,
        )
        .limit(1)
        .with_for_update()
    ).scalar_one_or_none()

    if existing_reservation is not None:
        log.info(
            "pos_claim: denied — item %d has ACTIVE reservation %s until %s",
            item_id, existing_reservation.id, existing_reservation.valid_until.isoformat(),
        )
        raise HTTPException(
            status_code=409,
            detail={
                "type":           "online_reservation",
                "reservation_id": existing_reservation.id,
                "reserved_until": existing_reservation.valid_until.isoformat(),
            },
        )

    # Layer 1: Lock ALL ACTIVE claims for this item — expired or not.
    # Holding this row lock serialises the sweep+insert pair across concurrent
    # requests.  If there are no ACTIVE rows, the lock covers nothing, and the
    # residual INSERT race falls through to Layer 2 (partial unique index).
    all_active_claims = db.execute(
        select(PosClaimRow)
        .where(
            PosClaimRow.item_id == item_id,
            PosClaimRow.status  == "ACTIVE",
        )
        .with_for_update()
    ).scalars().all()

    live_claims  = [c for c in all_active_claims if _normalize_to_utc(c.expires_at) > now]
    stale_claims = [c for c in all_active_claims if _normalize_to_utc(c.expires_at) <= now]

    if live_claims:
        existing_claim = live_claims[0]
        log.info(
            "pos_claim: denied — item %d already claimed (%s) until %s",
            item_id, existing_claim.id,
            _normalize_to_utc(existing_claim.expires_at).isoformat(),
        )
        raise HTTPException(
            status_code=409,
            detail={
                "type":       "pos_claim",
                "claim_id":   existing_claim.id,
                "expires_at": _normalize_to_utc(existing_claim.expires_at).isoformat(),
            },
        )

    # Sweep expired ACTIVE rows under the lock so the partial unique index
    # slot is free for the new INSERT (all in the same transaction).
    for stale in stale_claims:
        stale.status = "EXPIRED"

    ttl = max(1, min(body.ttl_seconds, 300))  # clamp 1–300 s
    claim = PosClaimRow(
        id=f"CLM-{uuid4().hex[:16]}",
        item_id=item_id,
        claimed_at=now,
        expires_at=now + timedelta(seconds=ttl),
        status="ACTIVE",
    )
    db.add(claim)
    try:
        db.commit()
    except IntegrityError:
        # Layer 2: partial unique index fired — another transaction inserted
        # an ACTIVE claim between our SELECT and our INSERT.
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "type":    "pos_claim",
                "message": "Concurrent claim — another POS request claimed this item.",
            },
        )

    log.info(
        "pos_claim: granted — item %d claim %s expires %s",
        item_id, claim.id, claim.expires_at.isoformat(),
    )
    return PosClaimResponse(
        claim_id=claim.id,
        item_id=item_id,
        expires_at=claim.expires_at,
    )


@router.post(
    "/items/{item_id}/pos-claim/{claim_id}/confirm",
    response_model=PosClaimStatusResponse,
    summary="Confirm a POS claim after the ERP invoice is committed",
)
def confirm_pos_claim(
    item_id:  int,
    claim_id: str,
    db:       Session = Depends(get_db),
    _:        None    = Depends(require_pos_auth),
) -> PosClaimStatusResponse:
    """Mark a claim CONFIRMED once the ERP invoice commit succeeds.

    Returns:
        200 — claim confirmed
        404 — claim not found for this item
        422 — claim is expired or not in ACTIVE status
    """
    now = datetime.now(timezone.utc)
    claim = db.execute(
        select(PosClaimRow).where(
            PosClaimRow.id      == claim_id,
            PosClaimRow.item_id == item_id,
        )
    ).scalar_one_or_none()

    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")

    if claim.status != "ACTIVE":
        raise HTTPException(
            status_code=422,
            detail=f"Claim is not ACTIVE (current status: {claim.status})",
        )

    if _normalize_to_utc(claim.expires_at) <= now:
        claim.status = "EXPIRED"
        db.commit()
        raise HTTPException(
            status_code=422,
            detail=f"Claim expired at {claim.expires_at.isoformat()}",
        )

    claim.status = "CONFIRMED"
    db.commit()
    log.info("pos_claim: confirmed — item %d claim %s", item_id, claim_id)
    return PosClaimStatusResponse(claim_id=claim_id, status="CONFIRMED")


@router.delete(
    "/items/{item_id}/pos-claim/{claim_id}",
    status_code=204,
    summary="Release a POS claim when the ERP sale is rolled back",
)
def release_pos_claim(
    item_id:  int,
    claim_id: str,
    db:       Session = Depends(get_db),
    _:        None    = Depends(require_pos_auth),
) -> None:
    """Mark a claim RELEASED when the ERP invoice is rolled back.

    The item immediately becomes claimable again. If the ERP crashes without
    calling this endpoint, the claim expires naturally after ttl_seconds.

    Returns:
        204 — claim released (or already in a terminal state)
        404 — claim not found for this item
    """
    claim = db.execute(
        select(PosClaimRow).where(
            PosClaimRow.id      == claim_id,
            PosClaimRow.item_id == item_id,
        )
    ).scalar_one_or_none()

    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")

    if claim.status == "ACTIVE":
        claim.status = "RELEASED"
        db.commit()
        log.info("pos_claim: released — item %d claim %s", item_id, claim_id)
