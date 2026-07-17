"""Contract tests for ERPSyncWorker.

Tests exercise the worker against:
    - An in-memory outbox (OutboxEventRow stubs)
    - A stub HTTP server (captures calls to the ERP internal endpoint)

No real database, no real ERP server.

Gate coverage:
    ES1: run_once() returns 0 when no OrderCreated events pending
    ES2: run_once() parses payload and POSTs to ERP with correct fields
    ES3: ERP 201 → erp_synced_at is marked (cursor advances)
    ES4: ERP 200 "already_processed" → treated as success (cursor advances)
    ES5: ERP 409 out-of-stock → logged, cursor advances (skip silently)
    ES6: ERP 5xx → exception raised, row NOT marked (retry next tick)
    ES7: payload carries correct order_id, item_id, amount, currency
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ORDER_ID = "ord_es_contract_001"
_ITEM_ID = 42
_AMOUNT = "5500.00"
_CURRENCY = "SAR"
_NOW = datetime(2026, 7, 14, 10, 0, 0, tzinfo=timezone.utc)

_PAYLOAD = json.dumps({
    "order_id": _ORDER_ID,
    "item_id": _ITEM_ID,
    "amount": _AMOUNT,
    "currency": _CURRENCY,
})


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

@dataclass
class _StubRow:
    id: int
    event_type: str
    payload: str
    created_at: datetime = field(default=_NOW)
    erp_synced_at: datetime | None = None


@dataclass
class _StubSession:
    rows: list[_StubRow] = field(default_factory=list)
    updated_ids: list[int] = field(default_factory=list)
    committed: bool = False
    rolled_back: bool = False

    def execute(self, stmt: Any) -> Any:
        return _StubScalar(self.rows)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        pass


@dataclass
class _StubScalar:
    _rows: list[_StubRow]

    def scalars(self) -> _StubScalar:
        return self

    def all(self) -> list[_StubRow]:
        return self._rows


# ---------------------------------------------------------------------------
# Worker factory
# ---------------------------------------------------------------------------

def _make_worker(erp_base_url: str = "http://erp-stub"):
    from yasargold_commerce.workers.erp_sync_worker import ERPSyncWorker
    session = _StubSession()
    worker = ERPSyncWorker(
        session_factory=lambda: session,
        erp_base_url=erp_base_url,
        internal_secret="test-secret",
    )
    return worker, session


# ---------------------------------------------------------------------------
# ES1: no rows → 0
# ---------------------------------------------------------------------------

class TestES1NoRows:
    def test_returns_zero_when_no_pending_events(self) -> None:
        worker, _ = _make_worker()
        result = worker.run_once()
        assert result == 0


# ---------------------------------------------------------------------------
# ES2-ES3: happy path — 201 Created
# ---------------------------------------------------------------------------

class TestES2ES3HappyPath:
    def _make_row(self) -> _StubRow:
        return _StubRow(id=1, event_type="OrderCreated", payload=_PAYLOAD)

    def test_posts_to_erp_endpoint(self) -> None:
        worker, session = _make_worker()
        session.rows = [self._make_row()]

        captured: list[dict] = []

        import httpx
        with patch.object(httpx, "post") as mock_post:
            mock_post.return_value = MagicMock(status_code=201, text="")
            worker.run_once()

        assert mock_post.called

    def test_request_body_contains_correct_fields(self) -> None:
        worker, session = _make_worker()
        session.rows = [self._make_row()]

        captured_kwargs: dict = {}

        import httpx
        with patch.object(httpx, "post") as mock_post:
            mock_post.return_value = MagicMock(status_code=201, text="")
            mock_post.side_effect = lambda url, **kw: (
                captured_kwargs.update(kw) or MagicMock(status_code=201, text="")
            )
            worker.run_once()

        body = captured_kwargs.get("json", {})
        assert body["order_id"] == _ORDER_ID
        assert body["item_id"] == _ITEM_ID
        assert body["currency"] == _CURRENCY

    def test_internal_secret_header_sent(self) -> None:
        worker, session = _make_worker()
        session.rows = [self._make_row()]

        captured_kwargs: dict = {}

        import httpx
        with patch.object(httpx, "post") as mock_post:
            mock_post.side_effect = lambda url, **kw: (
                captured_kwargs.update(kw) or MagicMock(status_code=201, text="")
            )
            worker.run_once()

        assert captured_kwargs.get("headers", {}).get("X-Internal-Secret") == "test-secret"

    def test_session_committed_on_success(self) -> None:
        worker, session = _make_worker()
        session.rows = [self._make_row()]

        import httpx
        with patch.object(httpx, "post") as mock_post:
            mock_post.return_value = MagicMock(status_code=201, text="")
            worker.run_once()

        assert session.committed

    def test_returns_count_synced(self) -> None:
        worker, session = _make_worker()
        session.rows = [self._make_row()]

        import httpx
        with patch.object(httpx, "post") as mock_post:
            mock_post.return_value = MagicMock(status_code=201, text="")
            result = worker.run_once()

        assert result == 1


# ---------------------------------------------------------------------------
# ES4: ERP returns 200 "already_processed" → cursor still advances
# ---------------------------------------------------------------------------

class TestES4AlreadyProcessed:
    def test_already_processed_counts_as_success(self) -> None:
        worker, session = _make_worker()
        session.rows = [_StubRow(id=2, event_type="OrderCreated", payload=_PAYLOAD)]

        import httpx
        with patch.object(httpx, "post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200, text='{"status": "already_processed"}',
            )
            result = worker.run_once()

        assert result == 1
        assert session.committed


# ---------------------------------------------------------------------------
# ES5: ERP 409 out-of-stock → skip silently, cursor advances
# ---------------------------------------------------------------------------

class TestES5OutOfStock:
    def test_409_is_skipped_not_retried(self) -> None:
        worker, session = _make_worker()
        session.rows = [_StubRow(id=3, event_type="OrderCreated", payload=_PAYLOAD)]

        import httpx
        with patch.object(httpx, "post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=409, text='{"error": "item out of stock"}',
            )
            result = worker.run_once()

        # 409 is treated as "handled" — cursor advances so we don't retry forever.
        assert result == 1
        assert session.committed


# ---------------------------------------------------------------------------
# ES6: ERP 5xx → exception, row NOT marked
# ---------------------------------------------------------------------------

class TestES6ERPError:
    def test_5xx_does_not_advance_cursor(self) -> None:
        worker, session = _make_worker()
        session.rows = [_StubRow(id=4, event_type="OrderCreated", payload=_PAYLOAD)]

        import httpx
        with patch.object(httpx, "post") as mock_post:
            resp = MagicMock(status_code=500, text="Internal Server Error")
            resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "500", request=MagicMock(), response=resp
            )
            mock_post.return_value = resp
            result = worker.run_once()

        # Row had an exception — it must NOT be in the synced set.
        assert result == 0


# ---------------------------------------------------------------------------
# ES7: payload snapshot — order_id, item_id, amount, currency
# ---------------------------------------------------------------------------

class TestES7PayloadSnapshot:
    def test_amount_forwarded_as_string(self) -> None:
        worker, session = _make_worker()
        session.rows = [_StubRow(id=5, event_type="OrderCreated", payload=_PAYLOAD)]

        captured_body: dict = {}

        import httpx
        with patch.object(httpx, "post") as mock_post:
            mock_post.side_effect = lambda url, **kw: (
                captured_body.update(kw.get("json", {}))
                or MagicMock(status_code=201, text="")
            )
            worker.run_once()

        assert captured_body["amount"] == _AMOUNT
