"""Reservations router — POST /api/v1/reservations.

Reference implementation for all write endpoints in the Commerce API.
The pattern here (with uow: / service.reserve() / uow.commit()) must be
replicated by Checkout, Returns, and all future write endpoints.

HTTP layer responsibilities:
  - Validate request shape (Pydantic)
  - Load domain objects from DB (item + gold price → Quote)
  - Open Unit of Work and call the domain service
  - Map domain exceptions to HTTP status codes
  - Commit and return 201

HTTP layer does NOT:
  - Make business decisions (domain service does)
  - Know pricing rules (domain engine does)
  - Know policy ordering (CompositePolicy does)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException

from yasargold_commerce.auth import get_customer_ref
from pydantic import BaseModel, field_serializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from yasargold_commerce.db import get_db
from yasargold_commerce.infra.pos_claim_orm import PosClaimRow
from yasargold_commerce.infra.reservation_uow import SQLAlchemyReservationUnitOfWork
from yasargold_commerce.models import GoldPrice, Item
from yasargold_domain.pricing.engine import PRICING_ENGINE_VERSION, karat_rate
from yasargold_domain.pricing.quotes import Quote, QuoteStatus
from yasargold_domain.pricing.reservation_policy import CompositePolicy, DefaultQuotePolicy
from yasargold_domain.reservation.exceptions import (
    ItemAlreadyReservedException,
    ReservationDenied,
)
from yasargold_domain.reservation.service import ReservationService
from yasargold_domain.reservation.unit_of_work import ReservationUnitOfWork
from yasargold_domain.shared.identifiers import ItemId
from yasargold_commerce.metrics import (
    QUOTE_AGE_SECONDS,
    RESERVATION_CONFLICT,
    RESERVATION_POLICY_DENIED,
    RESERVATION_SUCCESS,
)

router = APIRouter(prefix="/api/v1", tags=["reservations"])

_RESERVATION_WINDOW = timedelta(minutes=15)
_FRESH_TTL = timedelta(seconds=90)
_STALE_TTL = timedelta(minutes=5)

_reservation_service = ReservationService(
    policy=CompositePolicy(policies=[DefaultQuotePolicy()])
)


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class CreateReservationRequest(BaseModel):
    item_slug: str
    customer_phone: str | None = None  # E.164 format preferred; used for order notifications


class ReservationCreatedResponse(BaseModel):
    reservation_id: str
    quote_id: str
    item_slug: str
    locked_rate_per_gram_24k: Decimal
    karat_rate_per_gram: Decimal
    locked_total_sar: Decimal
    pricing_engine_version: str
    reserved_at: datetime
    valid_until: datetime

    @field_serializer("locked_rate_per_gram_24k", "karat_rate_per_gram", "locked_total_sar")
    def _serialize_decimal(self, v: Decimal) -> str:
        return str(v)


# ---------------------------------------------------------------------------
# Injectable dependencies (overridden in contract tests via dependency_overrides)
# ---------------------------------------------------------------------------

def _get_uow(db: Session = Depends(get_db)) -> ReservationUnitOfWork:
    """Return a UoW bound to the current request's DB session."""
    return SQLAlchemyReservationUnitOfWork(db)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_quote(item: Item, gp: GoldPrice, now: datetime) -> Quote:
    gp_date = gp.date if gp.date.tzinfo is not None else gp.date.replace(tzinfo=timezone.utc)
    age = now - gp_date
    if age <= _FRESH_TTL:
        status = QuoteStatus.FRESH
    elif age <= _STALE_TTL:
        status = QuoteStatus.STALE
    else:
        status = QuoteStatus.HALTED

    item_karat = int(item.karat) if item.karat and item.karat.isdigit() else 24
    gold_rate = Decimal(str(gp.price))

    return Quote(
        status=status,
        gold_price_id=gp.id,
        gold_rate_per_gram_24k=gold_rate,
        karat_rate_per_gram=karat_rate(gold_rate, item_karat),
        issued_at=now,
        valid_from=now,
        valid_until=now + _RESERVATION_WINDOW,
        pricing_engine_version=PRICING_ENGINE_VERSION,
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post(
    "/reservations",
    response_model=ReservationCreatedResponse,
    status_code=201,
    summary="Reserve a product at the current gold rate",
    responses={
        409: {"description": "Item already reserved"},
        422: {"description": "Policy rejection (expired, stale, halted)"},
        503: {"description": "Gold price unavailable"},
    },
)
def create_reservation(
    body: CreateReservationRequest,
    db: Session = Depends(get_db),
    uow: ReservationUnitOfWork = Depends(_get_uow),
    customer_ref: str = Depends(get_customer_ref),
) -> ReservationCreatedResponse:
    """Reserve a product at the current gold rate.

    The client sends only item_slug. All gold-price values are computed
    server-side — the client cannot influence the locked rate.

    Error codes returned in detail.code:
      QUOTE_STATUS_INVALID  — gold rate is stale or halted
      QUOTE_EXPIRED         — reservation window elapsed (rare on fresh issue)
      ITEM_ALREADY_RESERVED — another customer holds this item (HTTP 409)
    """
    now = datetime.now(timezone.utc)
    item_code = body.item_slug.upper()

    item = db.execute(select(Item).where(Item.item_code == item_code)).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail=f"Product '{body.item_slug}' not found")

    # ADR-013 Condition 1 — first of two availability checks.
    # Reads ERP stock from the shared items table (Commerce has read-only access).
    # Prevents creating a reservation for an item already sold at POS.
    if not item.stock or item.stock <= 0:
        raise HTTPException(
            status_code=409,
            detail={"code": "ITEM_NOT_AVAILABLE"},
        )

    # V3 mutual exclusion — POS claim blocks online reservation (INV-4 inverse).
    # If the showroom has an ACTIVE pos-claim on this item, the item is in the
    # process of being sold at the counter. Allowing a concurrent online
    # reservation would race the POS sale — the mirror of the problem pos-claim
    # solves. Reject immediately so the customer sees it before paying.
    active_pos_claim = db.execute(
        select(PosClaimRow)
        .where(
            PosClaimRow.item_id    == item.id,
            PosClaimRow.status     == "ACTIVE",
            PosClaimRow.expires_at >  now,
        )
        .limit(1)
    ).scalar_one_or_none()

    if active_pos_claim is not None:
        raise HTTPException(
            status_code=409,
            detail={"code": "ITEM_POS_CLAIMED"},
        )

    gp = db.execute(select(GoldPrice).order_by(GoldPrice.id.desc()).limit(1)).scalar_one_or_none()
    if gp is None:
        raise HTTPException(status_code=503, detail="Gold price unavailable")

    quote = _build_quote(item, gp, now)

    try:
        with uow:
            locked_quote, reservation_id = _reservation_service.reserve(
                quote, ItemId(item.id), uow, now=now,
                customer_phone=customer_ref,
            )
            uow.commit()
    except ReservationDenied as exc:
        RESERVATION_POLICY_DENIED.labels(reason=exc.reason.value).inc()
        raise HTTPException(
            status_code=422,
            detail={"code": exc.reason.value, "policy": exc.policy},
        )
    except ItemAlreadyReservedException:
        RESERVATION_CONFLICT.inc()
        raise HTTPException(
            status_code=409,
            detail={"code": "ITEM_ALREADY_RESERVED"},
        )

    RESERVATION_SUCCESS.inc()
    gp_date = gp.date if gp.date.tzinfo is not None else gp.date.replace(tzinfo=timezone.utc)
    QUOTE_AGE_SECONDS.observe((now - gp_date).total_seconds())

    net_gold = Decimal(str(
        ((item.weight or 0.0) - (item.stones_weight or 0.0)) if item.has_stones
        else (item.weight or 0.0)
    ))
    wage    = Decimal(str(item.wage or 0))
    stones  = Decimal(str(item.stones_value or 0)) if item.has_stones else Decimal("0")
    locked_total_sar = locked_quote.karat_rate_per_gram * net_gold + wage + stones

    return ReservationCreatedResponse(
        reservation_id=str(reservation_id),
        quote_id=str(locked_quote.id),
        item_slug=item.item_code.lower(),
        locked_rate_per_gram_24k=locked_quote.gold_rate_per_gram_24k,
        karat_rate_per_gram=locked_quote.karat_rate_per_gram,
        locked_total_sar=locked_total_sar,
        pricing_engine_version=locked_quote.pricing_engine_version,
        reserved_at=now,
        valid_until=locked_quote.valid_until,
    )
