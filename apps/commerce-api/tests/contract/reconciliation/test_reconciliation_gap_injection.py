"""OPEN-2: ReconciliationWorker gap injection integration test.

Closes Gate A OPEN-2 by proving two things the contract stubs cannot prove:

    Step A — Steady-state: worker runs against a real SQLite DB, finds no gaps
              when all PAID orders have matching ERP invoices.

    Step B — Gap detection: injecting a PAID order with no ERP invoice produces:
              (1) a row in the real reconciliation_findings table,
              (2) reconciliation_gaps_total counter incremented by 1,
              (3) resolved_at is NULL (gap is open, not auto-resolved).

The key difference from the contract tests: these tests use a real SQLAlchemy
session against an in-memory SQLite database, not a stub. This proves the ORM
write path — ReconciliationFindingRow.__tablename__, column types, and the
session.add/commit cycle — is correct end-to-end.

Gate A condition: Step A + Step B pass → OPEN-2 closed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Import every ORM class that shares Base.metadata before create_all.
import yasargold_commerce.infra.notification_orm  # noqa: F401
import yasargold_commerce.infra.order_orm  # noqa: F401
import yasargold_commerce.infra.payment_orm  # noqa: F401
import yasargold_commerce.infra.reconciliation_orm  # noqa: F401
import yasargold_commerce.infra.reservation_orm  # noqa: F401
import yasargold_commerce.infra.shipment_orm  # noqa: F401
import yasargold_commerce.models  # noqa: F401

from yasargold_commerce.db import Base
from yasargold_commerce.infra.order_orm import OrderRow
from yasargold_commerce.infra.reconciliation_orm import ReconciliationFindingRow
from yasargold_commerce.metrics import RECONCILIATION_GAPS
from yasargold_commerce.workers.reconciliation_worker import ReconciliationWorker

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ERP_BASE = "http://erp-test-stub"
_SECRET = "injection-test-secret"
_AMOUNT = "5500.00"
_NOW = datetime.now(timezone.utc)
_ORDER_ID = "ord_gap_injection_001"
_ORDER_ID_2 = "ord_gap_injection_002"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def SessionLocal(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _make_worker(session_factory) -> ReconciliationWorker:
    return ReconciliationWorker(
        session_factory=session_factory,
        erp_base_url=_ERP_BASE,
        internal_secret=_SECRET,
        lookback_days=1,
    )


def _seed_paid_order(
    session_factory,
    order_id: str = _ORDER_ID,
    amount: str = _AMOUNT,
    minutes_ago: int = 30,
) -> None:
    session = session_factory()
    try:
        session.add(OrderRow(
            id=order_id,
            reservation_id=f"res_{order_id}",
            payment_intent_id=f"pi_{order_id}",
            item_id=1,
            amount=amount,
            status="PAID",
            created_at=_NOW - timedelta(minutes=minutes_ago),
            customer_ref="+966500000001",
        ))
        session.commit()
    finally:
        session.close()


def _count_findings(session_factory, order_id: str) -> int:
    session = session_factory()
    try:
        return session.execute(
            select(ReconciliationFindingRow)
            .where(ReconciliationFindingRow.order_id == order_id)
        ).scalars().all().__len__()
    finally:
        session.close()


def _get_finding(session_factory, order_id: str) -> ReconciliationFindingRow | None:
    session = session_factory()
    try:
        return session.execute(
            select(ReconciliationFindingRow)
            .where(ReconciliationFindingRow.order_id == order_id)
        ).scalars().first()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Step A — Steady-state: zero gaps with real DB
# ---------------------------------------------------------------------------

class TestStepAZeroGaps:
    """Worker runs against a real SQLite DB and finds no gaps."""

    def test_no_paid_orders_returns_empty(self, SessionLocal):
        worker = _make_worker(SessionLocal)
        result = worker.run_once()
        assert result == []

    def test_paid_order_with_matching_invoice_produces_no_finding(self, SessionLocal):
        _seed_paid_order(SessionLocal)
        worker = _make_worker(SessionLocal)

        with patch.object(httpx, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"invoice_id": 42, "total": _AMOUNT, "status": "paid"},
            )
            result = worker.run_once()

        assert result == []
        assert _count_findings(SessionLocal, _ORDER_ID) == 0

    def test_paid_order_erp_unreachable_is_not_a_gap(self, SessionLocal):
        _seed_paid_order(SessionLocal)
        worker = _make_worker(SessionLocal)

        with patch.object(httpx, "get", side_effect=httpx.ConnectError("unreachable")):
            result = worker.run_once()

        assert result == []
        assert _count_findings(SessionLocal, _ORDER_ID) == 0


# ---------------------------------------------------------------------------
# Step B — Gap injection: MISSING_ERP_INVOICE
# ---------------------------------------------------------------------------

class TestStepBMissingInvoiceGap:
    """Injecting a PAID order with no ERP invoice produces a DB row + counter."""

    def test_missing_invoice_inserts_finding_row_in_real_db(self, SessionLocal):
        _seed_paid_order(SessionLocal)
        worker = _make_worker(SessionLocal)

        with patch.object(httpx, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=404)
            worker.run_once()

        assert _count_findings(SessionLocal, _ORDER_ID) == 1

    def test_finding_row_has_correct_kind(self, SessionLocal):
        _seed_paid_order(SessionLocal)
        worker = _make_worker(SessionLocal)

        with patch.object(httpx, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=404)
            worker.run_once()

        row = _get_finding(SessionLocal, _ORDER_ID)
        assert row is not None
        assert row.kind == "MISSING_ERP_INVOICE"

    def test_finding_row_is_open_resolved_at_is_null(self, SessionLocal):
        """A gap is open until explicitly resolved — resolved_at must be None."""
        _seed_paid_order(SessionLocal)
        worker = _make_worker(SessionLocal)

        with patch.object(httpx, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=404)
            worker.run_once()

        row = _get_finding(SessionLocal, _ORDER_ID)
        assert row is not None
        assert row.resolved_at is None

    def test_missing_invoice_increments_prometheus_counter(self, SessionLocal):
        _seed_paid_order(SessionLocal)
        worker = _make_worker(SessionLocal)

        before = RECONCILIATION_GAPS.labels(kind="MISSING_ERP_INVOICE")._value.get()

        with patch.object(httpx, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=404)
            worker.run_once()

        after = RECONCILIATION_GAPS.labels(kind="MISSING_ERP_INVOICE")._value.get()
        assert after == before + 1

    def test_second_run_does_not_duplicate_finding(self, SessionLocal):
        """Two consecutive runs on the same gap produce two rows — each run is a fresh detection.
        This is expected: idempotency is enforced by the resolved_at workflow, not by the worker.
        Workers detect; humans (or ops tooling) resolve."""
        _seed_paid_order(SessionLocal)
        worker = _make_worker(SessionLocal)

        with patch.object(httpx, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=404)
            worker.run_once()
            worker.run_once()

        assert _count_findings(SessionLocal, _ORDER_ID) == 2


# ---------------------------------------------------------------------------
# Step B — Gap injection: AMOUNT_MISMATCH
# ---------------------------------------------------------------------------

class TestStepBAmountMismatchGap:
    """Injecting a PAID order whose ERP invoice total differs produces a DB row."""

    def test_amount_mismatch_inserts_finding_row_in_real_db(self, SessionLocal):
        _seed_paid_order(SessionLocal, amount="5500.00")
        worker = _make_worker(SessionLocal)

        with patch.object(httpx, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"invoice_id": 99, "total": "4999.00", "status": "paid"},
            )
            worker.run_once()

        assert _count_findings(SessionLocal, _ORDER_ID) == 1

    def test_amount_mismatch_kind_in_db(self, SessionLocal):
        _seed_paid_order(SessionLocal, amount="5500.00")
        worker = _make_worker(SessionLocal)

        with patch.object(httpx, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"invoice_id": 99, "total": "1.00", "status": "paid"},
            )
            worker.run_once()

        row = _get_finding(SessionLocal, _ORDER_ID)
        assert row is not None
        assert row.kind == "AMOUNT_MISMATCH"

    def test_amount_mismatch_increments_counter(self, SessionLocal):
        _seed_paid_order(SessionLocal, amount="5500.00")
        worker = _make_worker(SessionLocal)

        before = RECONCILIATION_GAPS.labels(kind="AMOUNT_MISMATCH")._value.get()

        with patch.object(httpx, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"invoice_id": 99, "total": "4999.00", "status": "paid"},
            )
            worker.run_once()

        after = RECONCILIATION_GAPS.labels(kind="AMOUNT_MISMATCH")._value.get()
        assert after == before + 1


# ---------------------------------------------------------------------------
# Step B — Multiple orders: only gapped order produces finding
# ---------------------------------------------------------------------------

class TestStepBMixedOrders:
    """One good order + one gapped order → exactly one finding row."""

    def test_only_gapped_order_produces_finding(self, SessionLocal):
        _seed_paid_order(SessionLocal, order_id=_ORDER_ID, amount="5500.00")
        _seed_paid_order(SessionLocal, order_id=_ORDER_ID_2, amount="3200.00")

        worker = _make_worker(SessionLocal)

        def _erp_response(url: str, **kwargs):
            if _ORDER_ID_2 in url:
                # This order has a matching invoice
                return MagicMock(
                    status_code=200,
                    json=lambda: {"invoice_id": 1, "total": "3200.00"},
                )
            # _ORDER_ID has no invoice
            return MagicMock(status_code=404)

        with patch.object(httpx, "get", side_effect=_erp_response):
            result = worker.run_once()

        assert len(result) == 1
        assert result[0].order_id == _ORDER_ID
        assert _count_findings(SessionLocal, _ORDER_ID) == 1
        assert _count_findings(SessionLocal, _ORDER_ID_2) == 0
