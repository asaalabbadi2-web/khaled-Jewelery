"""ReconciliationWorker — daily Commerce orders vs ERP invoices audit.

Compares every PAID Commerce order against ERP invoices linked via
commerce_order_id.

Two discrepancy types:
    MISSING_ERP_INVOICE  — Commerce order is PAID but no ERP invoice exists.
                           Indicates ERPSyncWorker is behind or failed.
    AMOUNT_MISMATCH      — Invoice exists but total != order amount.
                           Indicates a data integrity problem.

Every discrepancy is:
  1. Written to reconciliation_findings (stays open until resolved_at is set).
  2. Counted in reconciliation_gaps_total Prometheus counter.
  3. Logged at ERROR level.

Alert rule: reconciliation_gaps_total > 0 → open incident. By the standard
in architecture-v1.md §4.6, a gap is either explained or it is an incident.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from yasargold_commerce.infra.order_orm import OrderRow
from yasargold_commerce.infra.pos_claim_orm import PosClaimRow
from yasargold_commerce.infra.reconciliation_orm import ReconciliationFindingRow
from yasargold_commerce.metrics import RECONCILIATION_GAPS, RECONCILIATION_ORDERS_CHECKED

log = logging.getLogger(__name__)


@dataclass
class Discrepancy:
    order_id: str
    kind: str        # "MISSING_ERP_INVOICE" | "AMOUNT_MISMATCH" | "ORPHANED_CLAIM"
    detail: str


class ReconciliationWorker:
    """Compares Commerce PAID orders against ERP invoices.

    Args:
        session_factory: SQLAlchemy sessionmaker (Commerce DB).
        erp_base_url:    Base URL of the ERP Flask server.
        internal_secret: ERP_INTERNAL_SECRET for X-Internal-Secret header.
        lookback_days:   How many days back to check (default: 1 = yesterday's orders).
        http_timeout:    Seconds for ERP API calls.
    """

    def __init__(
        self,
        session_factory: sessionmaker,
        erp_base_url: str | None = None,
        internal_secret: str | None = None,
        lookback_days: int = 1,
        http_timeout: float = 10.0,
    ) -> None:
        self._factory = session_factory
        self._erp_base_url = (erp_base_url or os.environ.get("ERP_BASE_URL", "")).rstrip("/")
        self._secret = internal_secret or os.environ.get("ERP_INTERNAL_SECRET", "")
        self._lookback_days = lookback_days
        self._timeout = http_timeout

    def run_once(self) -> list[Discrepancy]:
        """Run one reconciliation pass. Returns list of discrepancies found."""
        now = datetime.now(timezone.utc)  # clock-guard: boundary
        since = now - timedelta(days=self._lookback_days)

        session: Session = self._factory()
        try:
            # ── Order vs ERP invoice check ────────────────────────────────────
            rows = session.execute(
                select(OrderRow)
                .where(OrderRow.status == "PAID")
                .where(OrderRow.created_at >= since)
                .order_by(OrderRow.created_at)
            ).scalars().all()

            RECONCILIATION_ORDERS_CHECKED.inc(len(rows))

            discrepancies: list[Discrepancy] = []
            for order_row in rows:
                d = self._check_order(order_row)
                if d is not None:
                    discrepancies.append(d)

            # ── Orphaned pos-claim check (F1) ─────────────────────────────────
            # Detect ACTIVE claims past TTL where the ERP committed a sale but
            # the best-effort confirm call failed. The item appears available
            # online even though it is sold. Caught here; daily alert fires.
            claim_discrepancies = self._check_orphaned_pos_claims(session, now)
            discrepancies.extend(claim_discrepancies)

            # ── Persist all discrepancies ─────────────────────────────────────
            for d in discrepancies:
                log.error(
                    "reconciliation_worker: %s order=%s — %s",
                    d.kind, d.order_id, d.detail,
                )
                RECONCILIATION_GAPS.labels(kind=d.kind).inc()
                session.add(ReconciliationFindingRow(
                    order_id=d.order_id,
                    kind=d.kind,
                    detail=d.detail,
                    detected_at=now,
                ))

            if discrepancies:
                session.commit()
            else:
                log.info(
                    "reconciliation_worker: %d orders checked — all reconciled",
                    len(rows),
                )

            return discrepancies

        except Exception:
            session.rollback()
            log.exception("reconciliation_worker: pass failed, will retry next run")
            return []
        finally:
            session.close()

    def _check_order(self, order_row: OrderRow) -> Discrepancy | None:
        """Query ERP for the invoice linked to this order."""
        url = f"{self._erp_base_url}/api/internal/order-reconcile/{order_row.id}"
        try:
            resp = httpx.get(
                url,
                headers={"X-Internal-Secret": self._secret},
                timeout=self._timeout,
            )
        except Exception as exc:
            log.warning(
                "reconciliation_worker: ERP unreachable for order=%s — %s",
                order_row.id, exc,
            )
            return None  # Network issue — not a reconciliation discrepancy.

        if resp.status_code == 404:
            return Discrepancy(
                order_id=order_row.id,
                kind="MISSING_ERP_INVOICE",
                detail=(
                    f"No ERP invoice found for order {order_row.id} "
                    f"(amount={order_row.amount})"
                ),
            )

        if resp.status_code != 200:
            log.warning(
                "reconciliation_worker: unexpected status %s for order=%s",
                resp.status_code, order_row.id,
            )
            return None

        data = resp.json()
        erp_total = Decimal(str(data.get("total", "0")))
        order_amount = Decimal(str(order_row.amount))

        if erp_total != order_amount:
            return Discrepancy(
                order_id=order_row.id,
                kind="AMOUNT_MISMATCH",
                detail=(
                    f"Commerce amount={order_amount} != ERP total={erp_total} "
                    f"(invoice_id={data.get('invoice_id')})"
                ),
            )

        return None

    def _check_orphaned_pos_claims(
        self, session: Session, now: datetime
    ) -> list[Discrepancy]:
        """Detect zombie pos-claims: ACTIVE past TTL where ERP committed a sale.

        A zombie claim means `confirm_pos_claim()` failed after the ERP invoice
        committed. The claim TTL-expired still ACTIVE; the item now appears
        available online even though it was sold. This is the residual F1 window
        named in ADR-016 §N4.

        Grace period (5 min) absorbs confirm-call latency and retry attempts
        before we declare a claim orphaned.
        """
        grace = timedelta(minutes=5)
        zombies = session.execute(
            select(PosClaimRow)
            .where(PosClaimRow.status == "ACTIVE")
            .where(PosClaimRow.expires_at < now - grace)
        ).scalars().all()

        found: list[Discrepancy] = []
        for claim in zombies:
            d = self._check_pos_claim(claim)
            if d is not None:
                found.append(d)
        return found

    def _check_pos_claim(self, claim: PosClaimRow) -> Discrepancy | None:
        """Ask ERP if a sale was committed for this item after the claim was made."""
        url = f"{self._erp_base_url}/api/internal/item-sale/{claim.item_id}"
        try:
            resp = httpx.get(
                url,
                params={"after": claim.claimed_at.isoformat()},
                headers={"X-Internal-Secret": self._secret},
                timeout=self._timeout,
            )
        except Exception as exc:
            log.warning(
                "reconciliation_worker: ERP unreachable for claim=%s item=%d — %s",
                claim.id, claim.item_id, exc,
            )
            return None  # Network issue — not a confirmed discrepancy.

        if resp.status_code == 200:
            data = resp.json()
            return Discrepancy(
                order_id=claim.id,  # claim_id stored in the shared entity-id column
                kind="ORPHANED_CLAIM",
                detail=(
                    f"pos-claim {claim.id} for item {claim.item_id} expired without "
                    f"CONFIRMED but ERP has a committed sale "
                    f"(invoice_id={data.get('invoice_id')}, total={data.get('total')}). "
                    f"Item may appear available online until this gap is resolved. "
                    f"claimed_at={claim.claimed_at.isoformat()} "
                    f"expires_at={claim.expires_at.isoformat()}"
                ),
            )

        if resp.status_code == 404:
            return None  # No ERP sale — clean natural expiry, not a gap.

        log.warning(
            "reconciliation_worker: unexpected ERP status %d for claim=%s item=%d",
            resp.status_code, claim.id, claim.item_id,
        )
        return None
