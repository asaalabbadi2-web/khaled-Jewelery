"""Contract tests for ReconciliationWorker.

Tests exercise the worker against:
    - In-memory OrderRow stubs
    - A stub HTTP client (captures calls to ERP reconcile endpoint)
    - A stub session that records ReconciliationFindingRow inserts

No real database, no real ERP server.

Gate coverage:
    RC1: run_once() returns [] when no PAID orders in lookback window
    RC2: PAID order → ERP 200 matching amount → no discrepancy
    RC3: ERP 404 → MISSING_ERP_INVOICE discrepancy returned
    RC4: ERP 200 amount mismatch → AMOUNT_MISMATCH discrepancy returned
    RC5: discrepancy is written to ReconciliationFindingRow in the session
    RC6: discrepancy increments reconciliation_gaps_total Prometheus counter
    RC7: ERP unreachable (network error) → not counted as discrepancy
    RC8: reconciliation_orders_checked_total incremented per order checked
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ORDER_ID = "ord_rc_contract_001"
_AMOUNT = "5500.00"
_NOW = datetime(2026, 7, 14, 10, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

@dataclass
class _StubOrderRow:
    id: str
    status: str
    amount: str
    created_at: datetime = field(default=_NOW)


@dataclass
class _StubSession:
    rows: list[_StubOrderRow] = field(default_factory=list)
    added: list[Any] = field(default_factory=list)
    committed: bool = False

    def execute(self, stmt: Any) -> Any:
        return _StubScalar(self.rows)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


@dataclass
class _StubScalar:
    _rows: list

    def scalars(self) -> _StubScalar:
        return self

    def all(self) -> list:
        return self._rows


# ---------------------------------------------------------------------------
# Worker factory
# ---------------------------------------------------------------------------

def _make_worker(erp_base_url: str = "http://erp-stub"):
    from yasargold_commerce.workers.reconciliation_worker import ReconciliationWorker
    session = _StubSession()
    worker = ReconciliationWorker(
        session_factory=lambda: session,
        erp_base_url=erp_base_url,
        internal_secret="test-secret",
        lookback_days=1,
    )
    return worker, session


def _paid_order(order_id: str = _ORDER_ID, amount: str = _AMOUNT) -> _StubOrderRow:
    return _StubOrderRow(id=order_id, status="PAID", amount=amount)


# ---------------------------------------------------------------------------
# RC1: no PAID orders → []
# ---------------------------------------------------------------------------

class TestRC1NoOrders:
    def test_returns_empty_when_no_paid_orders(self) -> None:
        worker, _ = _make_worker()
        result = worker.run_once()
        assert result == []


# ---------------------------------------------------------------------------
# RC2: PAID order → ERP 200 matching → no discrepancy
# ---------------------------------------------------------------------------

class TestRC2HappyPath:
    def test_no_discrepancy_when_amounts_match(self) -> None:
        worker, session = _make_worker()
        session.rows = [_paid_order()]

        import httpx
        with patch.object(httpx, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"invoice_id": 1, "total": _AMOUNT, "status": "paid"},
            )
            result = worker.run_once()

        assert result == []
        assert session.added == []


# ---------------------------------------------------------------------------
# RC3: ERP 404 → MISSING_ERP_INVOICE
# ---------------------------------------------------------------------------

class TestRC3MissingInvoice:
    def test_missing_invoice_returned_as_discrepancy(self) -> None:
        worker, session = _make_worker()
        session.rows = [_paid_order()]

        import httpx
        with patch.object(httpx, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=404)
            result = worker.run_once()

        assert len(result) == 1
        assert result[0].kind == "MISSING_ERP_INVOICE"
        assert result[0].order_id == _ORDER_ID

    def test_missing_invoice_written_to_db(self) -> None:
        from yasargold_commerce.infra.reconciliation_orm import ReconciliationFindingRow
        worker, session = _make_worker()
        session.rows = [_paid_order()]

        import httpx
        with patch.object(httpx, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=404)
            worker.run_once()

        assert len(session.added) == 1
        added = session.added[0]
        assert isinstance(added, ReconciliationFindingRow)
        assert added.order_id == _ORDER_ID
        assert added.kind == "MISSING_ERP_INVOICE"
        assert added.resolved_at is None  # open until explained


# ---------------------------------------------------------------------------
# RC4: amount mismatch → AMOUNT_MISMATCH
# ---------------------------------------------------------------------------

class TestRC4AmountMismatch:
    def test_amount_mismatch_returned_as_discrepancy(self) -> None:
        worker, session = _make_worker()
        session.rows = [_paid_order(amount="5500.00")]

        import httpx
        with patch.object(httpx, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"invoice_id": 2, "total": "4999.00", "status": "paid"},
            )
            result = worker.run_once()

        assert len(result) == 1
        assert result[0].kind == "AMOUNT_MISMATCH"

    def test_amount_mismatch_written_to_db(self) -> None:
        from yasargold_commerce.infra.reconciliation_orm import ReconciliationFindingRow
        worker, session = _make_worker()
        session.rows = [_paid_order(amount="5500.00")]

        import httpx
        with patch.object(httpx, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"invoice_id": 2, "total": "4999.00", "status": "paid"},
            )
            worker.run_once()

        assert len(session.added) == 1
        added = session.added[0]
        assert isinstance(added, ReconciliationFindingRow)
        assert added.kind == "AMOUNT_MISMATCH"


# ---------------------------------------------------------------------------
# RC5: DB commit only when discrepancy exists
# ---------------------------------------------------------------------------

class TestRC5DBCommit:
    def test_session_committed_when_discrepancy_found(self) -> None:
        worker, session = _make_worker()
        session.rows = [_paid_order()]

        import httpx
        with patch.object(httpx, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=404)
            worker.run_once()

        assert session.committed

    def test_session_not_committed_when_no_discrepancy(self) -> None:
        worker, session = _make_worker()
        session.rows = [_paid_order()]

        import httpx
        with patch.object(httpx, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"invoice_id": 1, "total": _AMOUNT, "status": "paid"},
            )
            worker.run_once()

        assert not session.committed


# ---------------------------------------------------------------------------
# RC6: Prometheus counter incremented on discrepancy
# ---------------------------------------------------------------------------

class TestRC6PrometheusCounter:
    def test_reconciliation_gaps_incremented_on_missing_invoice(self) -> None:
        from yasargold_commerce.metrics import RECONCILIATION_GAPS
        worker, session = _make_worker()
        session.rows = [_paid_order()]

        before = RECONCILIATION_GAPS.labels(kind="MISSING_ERP_INVOICE")._value.get()

        import httpx
        with patch.object(httpx, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=404)
            worker.run_once()

        after = RECONCILIATION_GAPS.labels(kind="MISSING_ERP_INVOICE")._value.get()
        assert after == before + 1

    def test_reconciliation_gaps_incremented_on_amount_mismatch(self) -> None:
        from yasargold_commerce.metrics import RECONCILIATION_GAPS
        worker, session = _make_worker()
        session.rows = [_paid_order(amount="5500.00")]

        before = RECONCILIATION_GAPS.labels(kind="AMOUNT_MISMATCH")._value.get()

        import httpx
        with patch.object(httpx, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"invoice_id": 2, "total": "1.00", "status": "paid"},
            )
            worker.run_once()

        after = RECONCILIATION_GAPS.labels(kind="AMOUNT_MISMATCH")._value.get()
        assert after == before + 1


# ---------------------------------------------------------------------------
# RC7: ERP unreachable → not a discrepancy
# ---------------------------------------------------------------------------

class TestRC7NetworkError:
    def test_network_error_is_not_a_discrepancy(self) -> None:
        import httpx
        worker, session = _make_worker()
        session.rows = [_paid_order()]

        with patch.object(httpx, "get", side_effect=httpx.ConnectError("timeout")):
            result = worker.run_once()

        assert result == []
        assert session.added == []


# ---------------------------------------------------------------------------
# RC8: orders_checked counter
# ---------------------------------------------------------------------------

class TestRC8OrdersCheckedCounter:
    def test_orders_checked_incremented(self) -> None:
        from yasargold_commerce.metrics import RECONCILIATION_ORDERS_CHECKED
        worker, session = _make_worker()
        session.rows = [_paid_order("a"), _paid_order("b"), _paid_order("c")]

        before = RECONCILIATION_ORDERS_CHECKED._value.get()

        import httpx
        with patch.object(httpx, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"invoice_id": 9, "total": _AMOUNT, "status": "paid"},
            )
            worker.run_once()

        after = RECONCILIATION_ORDERS_CHECKED._value.get()
        assert after == before + 3
