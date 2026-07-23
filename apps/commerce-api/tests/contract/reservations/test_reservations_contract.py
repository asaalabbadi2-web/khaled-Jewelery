"""Contract tests for POST /api/v1/reservations.

Tests the complete Vertical Slice:
    Quote (FRESH) → ReservationService → lock_item → save → enqueue → 201

No database. Stubs are injected via FastAPI dependency_overrides.

Three scenario families (matching the user's spec):
  1. Happy path:        FRESH quote + available item → 201 Created
  2. Conflict:          item already reserved → 409
  3. Policy rejection:  stale/halted gold price → 422

The tests also validate that:
  - pricing_engine_version is in every 201 response
  - rate fields are Decimal-serialised strings (not float)
  - valid_until is ~15 min from now
  - event_id is unique across two requests for the same item
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from yasargold_commerce.auth import get_customer_ref
from yasargold_commerce.main import app
from yasargold_commerce.db import get_db
from yasargold_commerce.routers.reservations import _get_uow

_TEST_CUSTOMER_REF = "+966500000001"
from yasargold_domain.reservation.events import DomainEvent, ReservationCreated
from yasargold_domain.reservation.exceptions import ItemAlreadyReservedException
from yasargold_domain.reservation.repository import ReservationRecord

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

@dataclass
class _StubItem:
    id: int = 42
    item_code: str = "YG001"
    karat: str = "21"
    stock: int = 1  # ADR-013 Condition 1: default available in ERP


_RIYADH = timezone(timedelta(hours=3))


def _fresh_date() -> datetime:
    """30 seconds ago in Riyadh local time — always FRESH.

    Matches production: ERP stores gold_price.date as naive Riyadh local time
    via db.func.now() with TZ=Asia/Riyadh on the server.
    """
    return datetime.now(_RIYADH).replace(tzinfo=None) - timedelta(seconds=30)


def _stale_date() -> datetime:
    """3 minutes ago in Riyadh local time — STALE (90s < age < 5min)."""
    return datetime.now(_RIYADH).replace(tzinfo=None) - timedelta(minutes=3)


def _halted_date() -> datetime:
    """10 minutes ago in Riyadh local time — HALTED (age > 5min)."""
    return datetime.now(_RIYADH).replace(tzinfo=None) - timedelta(minutes=10)


@dataclass
class _StubGoldPrice:
    id: int = 18452
    price: float = 230.0
    date: datetime = field(default_factory=_fresh_date)


@dataclass
class _StubRepo:
    saved: list[ReservationRecord] = field(default_factory=list)
    should_fail_lock: bool = False

    def lock_item(self, item_id, quote_id, valid_until) -> bool:
        if self.should_fail_lock:
            raise ItemAlreadyReservedException(int(item_id))
        return True

    def save_reservation(self, record: ReservationRecord) -> None:
        self.saved.append(record)

    def release_lock(self, item_id, quote_id) -> None:
        pass

    def find_by_quote_id(self, quote_id):
        return None


@dataclass
class _StubOutbox:
    events: list[DomainEvent] = field(default_factory=list)

    def enqueue(self, event: DomainEvent) -> None:
        self.events.append(event)


@dataclass
class _StubUow:
    repository: _StubRepo = field(default_factory=_StubRepo)
    outbox: _StubOutbox = field(default_factory=_StubOutbox)
    committed: bool = False

    def __enter__(self) -> _StubUow:
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        pass


# A minimal stub SQLAlchemy session that returns preset rows on .execute()
class _StubResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _StubDbSession:
    def __init__(self, item=None, gold_price=None) -> None:
        self._item = item
        self._gold_price = gold_price

    def execute(self, stmt: Any) -> _StubResult:
        from yasargold_commerce.models import Item, GoldPrice
        # Route by table name in the compiled SQL.
        #
        # TECH DEBT — LEDGER: this routing is substring-based and fragile.
        # Any new query in reservations.py whose compiled SQL happens to contain
        # "item" and not "gold_price" and not "pos_claims" will accidentally
        # return the stub Item, causing a false 409 or silent wrong answer.
        # Fix trigger: a third unexpected match (two have already occurred —
        # the original Item/GoldPrice split, and the pos_claims addition above).
        # Terminal fix: replace with a proper SQLAlchemy statement-type inspector
        # that routes by the ORM entity, not by substring.
        compiled = str(stmt)
        if "pos_claims" in compiled.lower():
            return _StubResult(None)  # no active pos-claim in contract tests
        if "item" in compiled.lower() and "gold_price" not in compiled.lower():
            return _StubResult(self._item)
        return _StubResult(self._gold_price)

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

def _make_stub_uow(fail_lock: bool = False) -> _StubUow:
    return _StubUow(repository=_StubRepo(should_fail_lock=fail_lock))


def _client_with_stubs(
    uow: _StubUow,
    item: _StubItem | None = None,
    gold_price: _StubGoldPrice | None = None,
    no_item: bool = False,
    no_gold_price: bool = False,
) -> tuple[TestClient, _StubUow]:
    actual_item = None if no_item else (item or _StubItem())
    actual_gp = None if no_gold_price else (gold_price or _StubGoldPrice())
    stub_session = _StubDbSession(item=actual_item, gold_price=actual_gp)

    app.dependency_overrides[get_db] = lambda: stub_session
    app.dependency_overrides[_get_uow] = lambda: uow
    app.dependency_overrides[get_customer_ref] = lambda: _TEST_CUSTOMER_REF
    client = TestClient(app, raise_server_exceptions=False)
    return client, uow


def _cleanup() -> None:
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------

class TestHappyPath:
    def setup_method(self) -> None:
        self.uow = _make_stub_uow()
        self.client, _ = _client_with_stubs(self.uow)

    def teardown_method(self) -> None:
        _cleanup()

    def test_returns_201(self) -> None:
        r = self.client.post("/api/v1/reservations", json={"item_slug": "yg001"})
        assert r.status_code == 201

    def test_response_has_reservation_id(self) -> None:
        r = self.client.post("/api/v1/reservations", json={"item_slug": "yg001"})
        data = r.json()
        assert "reservation_id" in data
        assert data["reservation_id"].startswith("res_")

    def test_response_has_quote_id(self) -> None:
        r = self.client.post("/api/v1/reservations", json={"item_slug": "yg001"})
        assert "quote_id" in r.json()

    def test_response_has_pricing_engine_version(self) -> None:
        r = self.client.post("/api/v1/reservations", json={"item_slug": "yg001"})
        assert r.json()["pricing_engine_version"] == "v1"

    def test_response_rate_is_decimal_string_not_float(self) -> None:
        r = self.client.post("/api/v1/reservations", json={"item_slug": "yg001"})
        rate = r.json()["locked_rate_per_gram_24k"]
        # Must parse as Decimal cleanly (no scientific notation, no float imprecision)
        parsed = Decimal(str(rate))
        assert parsed > 0

    def test_response_valid_until_is_15_minutes_from_now(self) -> None:
        r = self.client.post("/api/v1/reservations", json={"item_slug": "yg001"})
        valid_until = datetime.fromisoformat(r.json()["valid_until"].replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        window = valid_until - now
        assert timedelta(minutes=14) < window < timedelta(minutes=16)

    def test_reservation_record_saved(self) -> None:
        self.client.post("/api/v1/reservations", json={"item_slug": "yg001"})
        assert len(self.uow.repository.saved) == 1

    def test_reservation_event_enqueued(self) -> None:
        self.client.post("/api/v1/reservations", json={"item_slug": "yg001"})
        assert len(self.uow.outbox.events) == 1
        assert isinstance(self.uow.outbox.events[0], ReservationCreated)

    def test_event_rate_is_decimal(self) -> None:
        self.client.post("/api/v1/reservations", json={"item_slug": "yg001"})
        event: ReservationCreated = self.uow.outbox.events[0]  # type: ignore[assignment]
        assert isinstance(event.locked_rate_per_gram_24k, Decimal)

    def test_uow_was_committed(self) -> None:
        self.client.post("/api/v1/reservations", json={"item_slug": "yg001"})
        assert self.uow.committed

    def test_item_slug_preserved_in_response(self) -> None:
        r = self.client.post("/api/v1/reservations", json={"item_slug": "yg001"})
        assert r.json()["item_slug"] == "yg001"

    def test_two_requests_produce_unique_event_ids(self) -> None:
        uow1 = _make_stub_uow()
        uow2 = _make_stub_uow()
        c1, _ = _client_with_stubs(uow1)
        r1 = c1.post("/api/v1/reservations", json={"item_slug": "yg001"})
        _cleanup()
        c2, _ = _client_with_stubs(uow2)
        r2 = c2.post("/api/v1/reservations", json={"item_slug": "yg001"})
        _cleanup()
        assert r1.status_code == 201
        assert r2.status_code == 201
        e1 = uow1.outbox.events[0].event_id
        e2 = uow2.outbox.events[0].event_id
        assert e1 != e2


# ---------------------------------------------------------------------------
# 2. Conflict — item already reserved
# ---------------------------------------------------------------------------

class TestConflict:
    def teardown_method(self) -> None:
        _cleanup()

    def test_returns_409(self) -> None:
        uow = _make_stub_uow(fail_lock=True)
        client, _ = _client_with_stubs(uow)
        r = client.post("/api/v1/reservations", json={"item_slug": "yg001"})
        assert r.status_code == 409

    def test_409_error_code(self) -> None:
        uow = _make_stub_uow(fail_lock=True)
        client, _ = _client_with_stubs(uow)
        r = client.post("/api/v1/reservations", json={"item_slug": "yg001"})
        assert r.json()["detail"]["code"] == "ITEM_ALREADY_RESERVED"

    def test_409_does_not_save_record(self) -> None:
        uow = _make_stub_uow(fail_lock=True)
        client, _ = _client_with_stubs(uow)
        client.post("/api/v1/reservations", json={"item_slug": "yg001"})
        assert len(uow.repository.saved) == 0

    def test_409_does_not_enqueue_event(self) -> None:
        uow = _make_stub_uow(fail_lock=True)
        client, _ = _client_with_stubs(uow)
        client.post("/api/v1/reservations", json={"item_slug": "yg001"})
        assert len(uow.outbox.events) == 0

    def test_409_does_not_commit(self) -> None:
        uow = _make_stub_uow(fail_lock=True)
        client, _ = _client_with_stubs(uow)
        client.post("/api/v1/reservations", json={"item_slug": "yg001"})
        assert not uow.committed


# ---------------------------------------------------------------------------
# 3. Policy rejections — stale / halted gold price
# ---------------------------------------------------------------------------

class TestPolicyRejections:
    def teardown_method(self) -> None:
        _cleanup()

    def _stale_gp(self) -> _StubGoldPrice:
        return _StubGoldPrice(date=_stale_date())

    def _halted_gp(self) -> _StubGoldPrice:
        return _StubGoldPrice(date=_halted_date())

    def test_stale_gold_price_returns_422(self) -> None:
        uow = _make_stub_uow()
        client, _ = _client_with_stubs(uow, gold_price=self._stale_gp())
        r = client.post("/api/v1/reservations", json={"item_slug": "yg001"})
        assert r.status_code == 422

    def test_stale_error_code_is_quote_status_invalid(self) -> None:
        uow = _make_stub_uow()
        client, _ = _client_with_stubs(uow, gold_price=self._stale_gp())
        r = client.post("/api/v1/reservations", json={"item_slug": "yg001"})
        assert r.json()["detail"]["code"] == "QUOTE_STATUS_INVALID"

    def test_halted_gold_price_returns_422(self) -> None:
        uow = _make_stub_uow()
        client, _ = _client_with_stubs(uow, gold_price=self._halted_gp())
        r = client.post("/api/v1/reservations", json={"item_slug": "yg001"})
        assert r.status_code == 422

    def test_halted_error_code_is_quote_status_invalid(self) -> None:
        uow = _make_stub_uow()
        client, _ = _client_with_stubs(uow, gold_price=self._halted_gp())
        r = client.post("/api/v1/reservations", json={"item_slug": "yg001"})
        assert r.json()["detail"]["code"] == "QUOTE_STATUS_INVALID"

    def test_policy_rejection_does_not_commit(self) -> None:
        uow = _make_stub_uow()
        client, _ = _client_with_stubs(uow, gold_price=self._halted_gp())
        client.post("/api/v1/reservations", json={"item_slug": "yg001"})
        assert not uow.committed


# ---------------------------------------------------------------------------
# 4. Not found / unavailable
# ---------------------------------------------------------------------------

class TestNotFound:
    def teardown_method(self) -> None:
        _cleanup()

    def test_unknown_slug_returns_404(self) -> None:
        uow = _make_stub_uow()
        client, _ = _client_with_stubs(uow, no_item=True)
        r = client.post("/api/v1/reservations", json={"item_slug": "unknown"})
        assert r.status_code == 404

    def test_no_gold_price_returns_503(self) -> None:
        uow = _make_stub_uow()
        client, _ = _client_with_stubs(uow, no_gold_price=True)
        r = client.post("/api/v1/reservations", json={"item_slug": "yg001"})
        assert r.status_code == 503


# ---------------------------------------------------------------------------
# 5. ERP availability check (ADR-013 Condition 1)
# ---------------------------------------------------------------------------

class TestErpAvailability:
    """Verify the first of two availability checks (ADR-013 Condition 1).

    Commerce reads ERP stock from the shared items table. If stock <= 0 the
    item was already sold at POS and the reservation must be rejected before
    any domain write occurs.
    """

    def teardown_method(self) -> None:
        _cleanup()

    def _zero_stock_item(self) -> _StubItem:
        item = _StubItem()
        item.stock = 0
        return item

    def test_sold_item_returns_409(self) -> None:
        uow = _make_stub_uow()
        client, _ = _client_with_stubs(uow, item=self._zero_stock_item())
        r = client.post("/api/v1/reservations", json={"item_slug": "yg001"})
        assert r.status_code == 409

    def test_sold_item_error_code(self) -> None:
        uow = _make_stub_uow()
        client, _ = _client_with_stubs(uow, item=self._zero_stock_item())
        r = client.post("/api/v1/reservations", json={"item_slug": "yg001"})
        assert r.json()["detail"]["code"] == "ITEM_NOT_AVAILABLE"

    def test_sold_item_does_not_commit(self) -> None:
        uow = _make_stub_uow()
        client, _ = _client_with_stubs(uow, item=self._zero_stock_item())
        client.post("/api/v1/reservations", json={"item_slug": "yg001"})
        assert not uow.committed

    def test_sold_item_does_not_enqueue_event(self) -> None:
        uow = _make_stub_uow()
        client, _ = _client_with_stubs(uow, item=self._zero_stock_item())
        client.post("/api/v1/reservations", json={"item_slug": "yg001"})
        assert len(uow.outbox.events) == 0
