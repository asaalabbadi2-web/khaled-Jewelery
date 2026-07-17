"""Unit tests for ReservationService.

All stubs are pure Python — no mocking library, no database.
Each stub is the simplest possible implementation of its Protocol.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from yasargold_domain.pricing.quotes import Quote, QuoteStatus
from yasargold_domain.pricing.reservation_policy import (
    CompositePolicy,
    DefaultQuotePolicy,
    PolicyResult,
    ReservationRejectionReason,
)
from yasargold_domain.reservation.events import DomainEvent, ReservationCreated
from yasargold_domain.reservation.exceptions import ReservationDenied
from yasargold_domain.reservation.repository import ReservationRecord
from yasargold_domain.reservation.service import ReservationService
from yasargold_domain.shared.identifiers import GoldPriceId, ItemId, QuoteId, ReservationId

# ---------------------------------------------------------------------------
# Stubs — minimal Protocol implementations for testing
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc)
_ITEM_ID = ItemId(42)
_GOLD_PRICE_ID = GoldPriceId(18452)


@dataclass
class _StubRepository:
    locked: list[tuple[ItemId, QuoteId]] = field(default_factory=list)
    saved: list[ReservationRecord] = field(default_factory=list)
    should_fail_lock: bool = False

    def lock_item(self, item_id: ItemId, quote_id: QuoteId, valid_until: datetime) -> bool:
        if self.should_fail_lock:
            from yasargold_domain.reservation.exceptions import ItemAlreadyReservedException
            raise ItemAlreadyReservedException(item_id)
        self.locked.append((item_id, quote_id))
        return True

    def save_reservation(self, record: ReservationRecord) -> None:
        self.saved.append(record)

    def release_lock(self, item_id: ItemId, quote_id: QuoteId) -> None:
        self.locked = [(i, q) for i, q in self.locked if (i, q) != (item_id, quote_id)]

    def find_by_quote_id(self, quote_id: QuoteId) -> ReservationRecord | None:
        for r in self.saved:
            if r.quote_id == quote_id:
                return r
        return None


@dataclass
class _StubOutbox:
    events: list[DomainEvent] = field(default_factory=list)

    def enqueue(self, event: DomainEvent) -> None:
        self.events.append(event)


@dataclass
class _StubUow:
    repository: _StubRepository = field(default_factory=_StubRepository)
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


@dataclass
class _AlwaysDenyPolicy:
    reason: ReservationRejectionReason = ReservationRejectionReason.TRADING_HALTED

    def check(self, quote: Quote, item_id: int, now: datetime) -> PolicyResult:
        return PolicyResult.deny(self.reason, policy="_AlwaysDenyPolicy")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_quote(
    status: QuoteStatus = QuoteStatus.FRESH,
    minutes_until_expiry: int = 10,
    quote_id: QuoteId | None = None,
) -> Quote:
    valid_until = _NOW + timedelta(minutes=minutes_until_expiry)
    return Quote(
        status=status,
        gold_price_id=int(_GOLD_PRICE_ID),
        gold_rate_per_gram_24k=Decimal("230.00"),
        karat_rate_per_gram=Decimal("193.125"),
        issued_at=_NOW,
        valid_from=_NOW,
        valid_until=valid_until,
        pricing_engine_version="v1",
        id=quote_id,
        item_id=_ITEM_ID,
    )


def _make_service(policy=None) -> ReservationService:
    if policy is None:
        policy = CompositePolicy(policies=[DefaultQuotePolicy()])
    return ReservationService(policy=policy)


# ---------------------------------------------------------------------------
# Core flow
# ---------------------------------------------------------------------------

class TestReserveHappyPath:
    def test_returns_locked_quote(self):
        svc = _make_service()
        uow = _StubUow()
        locked_quote, _ = svc.reserve(_make_quote(), _ITEM_ID, uow, now=_NOW)
        assert locked_quote.status == QuoteStatus.LOCKED

    def test_returns_reservation_id(self):
        svc = _make_service()
        uow = _StubUow()
        _, reservation_id = svc.reserve(_make_quote(), _ITEM_ID, uow, now=_NOW)
        assert isinstance(reservation_id, str)
        assert reservation_id.startswith("res_")

    def test_returned_quote_has_id_assigned(self):
        svc = _make_service()
        uow = _StubUow()
        locked_quote, _ = svc.reserve(_make_quote(), _ITEM_ID, uow, now=_NOW)
        assert locked_quote.id is not None
        assert isinstance(locked_quote.id, str)

    def test_preserves_existing_quote_id(self):
        existing_id = QuoteId("qt_existing_123")
        svc = _make_service()
        uow = _StubUow()
        locked_quote, _ = svc.reserve(_make_quote(quote_id=existing_id), _ITEM_ID, uow, now=_NOW)
        assert locked_quote.id == existing_id

    def test_original_quote_is_unchanged(self):
        original = _make_quote()
        svc = _make_service()
        uow = _StubUow()
        svc.reserve(original, _ITEM_ID, uow, now=_NOW)
        assert original.status == QuoteStatus.FRESH
        assert original.id is None

    def test_locked_quote_rate_matches_original(self):
        svc = _make_service()
        uow = _StubUow()
        quote = _make_quote()
        locked_quote, _ = svc.reserve(quote, _ITEM_ID, uow, now=_NOW)
        assert locked_quote.gold_rate_per_gram_24k == quote.gold_rate_per_gram_24k
        assert locked_quote.karat_rate_per_gram == quote.karat_rate_per_gram
        assert locked_quote.pricing_engine_version == "v1"

    def test_locked_quote_rate_is_decimal(self):
        svc = _make_service()
        uow = _StubUow()
        locked_quote, _ = svc.reserve(_make_quote(), _ITEM_ID, uow, now=_NOW)
        assert isinstance(locked_quote.gold_rate_per_gram_24k, Decimal)


# ---------------------------------------------------------------------------
# Repository interactions
# ---------------------------------------------------------------------------

class TestRepositoryInteractions:
    def test_calls_lock_item(self):
        svc = _make_service()
        uow = _StubUow()
        svc.reserve(_make_quote(), _ITEM_ID, uow, now=_NOW)
        assert len(uow.repository.locked) == 1
        assert uow.repository.locked[0][0] == _ITEM_ID

    def test_saves_reservation_record(self):
        svc = _make_service()
        uow = _StubUow()
        svc.reserve(_make_quote(), _ITEM_ID, uow, now=_NOW)
        assert len(uow.repository.saved) == 1

    def test_saved_record_has_correct_fields(self):
        svc = _make_service()
        uow = _StubUow()
        quote = _make_quote()
        svc.reserve(quote, _ITEM_ID, uow, now=_NOW)
        record = uow.repository.saved[0]
        assert record.item_id == _ITEM_ID
        assert record.gold_price_id == _GOLD_PRICE_ID
        assert record.locked_rate_per_gram_24k == Decimal("230.00")
        assert record.pricing_engine_version == "v1"
        assert record.status == "ACTIVE"
        assert record.reserved_at == _NOW

    def test_saved_record_rate_is_decimal(self):
        svc = _make_service()
        uow = _StubUow()
        svc.reserve(_make_quote(), _ITEM_ID, uow, now=_NOW)
        assert isinstance(uow.repository.saved[0].locked_rate_per_gram_24k, Decimal)

    def test_lock_and_record_use_same_quote_id(self):
        svc = _make_service()
        uow = _StubUow()
        svc.reserve(_make_quote(), _ITEM_ID, uow, now=_NOW)
        locked_quote_id = uow.repository.locked[0][1]
        saved_quote_id = uow.repository.saved[0].quote_id
        assert locked_quote_id == saved_quote_id


# ---------------------------------------------------------------------------
# Outbox interactions
# ---------------------------------------------------------------------------

class TestOutboxInteractions:
    def test_enqueues_reservation_created_event(self):
        svc = _make_service()
        uow = _StubUow()
        svc.reserve(_make_quote(), _ITEM_ID, uow, now=_NOW)
        assert len(uow.outbox.events) == 1
        assert isinstance(uow.outbox.events[0], ReservationCreated)

    def test_event_carries_correct_item_id(self):
        svc = _make_service()
        uow = _StubUow()
        svc.reserve(_make_quote(), _ITEM_ID, uow, now=_NOW)
        event: ReservationCreated = uow.outbox.events[0]  # type: ignore[assignment]
        assert event.item_id == _ITEM_ID

    def test_event_carries_correct_gold_price_id(self):
        svc = _make_service()
        uow = _StubUow()
        svc.reserve(_make_quote(), _ITEM_ID, uow, now=_NOW)
        event: ReservationCreated = uow.outbox.events[0]  # type: ignore[assignment]
        assert event.gold_price_id == _GOLD_PRICE_ID

    def test_event_rate_is_decimal_not_float(self):
        svc = _make_service()
        uow = _StubUow()
        svc.reserve(_make_quote(), _ITEM_ID, uow, now=_NOW)
        event: ReservationCreated = uow.outbox.events[0]  # type: ignore[assignment]
        assert isinstance(event.locked_rate_per_gram_24k, Decimal)

    def test_event_quote_id_matches_record_quote_id(self):
        svc = _make_service()
        uow = _StubUow()
        svc.reserve(_make_quote(), _ITEM_ID, uow, now=_NOW)
        event_quote_id = uow.outbox.events[0].quote_id
        record_quote_id = uow.repository.saved[0].quote_id
        assert event_quote_id == record_quote_id

    def test_event_reservation_id_matches_record_id(self):
        svc = _make_service()
        uow = _StubUow()
        svc.reserve(_make_quote(), _ITEM_ID, uow, now=_NOW)
        event_res_id = uow.outbox.events[0].reservation_id
        record_res_id = uow.repository.saved[0].id
        assert event_res_id == record_res_id


# ---------------------------------------------------------------------------
# Policy rejections
# ---------------------------------------------------------------------------

class TestPolicyRejections:
    def test_expired_quote_raises_reservation_denied(self):
        svc = _make_service()
        uow = _StubUow()
        expired = _make_quote(minutes_until_expiry=-1)
        with pytest.raises(ReservationDenied) as exc_info:
            svc.reserve(expired, _ITEM_ID, uow, now=_NOW)
        assert exc_info.value.reason == ReservationRejectionReason.QUOTE_EXPIRED

    def test_stale_quote_raises_reservation_denied(self):
        svc = _make_service()
        uow = _StubUow()
        stale = _make_quote(status=QuoteStatus.STALE)
        with pytest.raises(ReservationDenied) as exc_info:
            svc.reserve(stale, _ITEM_ID, uow, now=_NOW)
        assert exc_info.value.reason == ReservationRejectionReason.QUOTE_STATUS_INVALID

    def test_halted_quote_raises_reservation_denied(self):
        svc = _make_service()
        uow = _StubUow()
        halted = _make_quote(status=QuoteStatus.HALTED)
        with pytest.raises(ReservationDenied) as exc_info:
            svc.reserve(halted, _ITEM_ID, uow, now=_NOW)
        assert exc_info.value.reason == ReservationRejectionReason.QUOTE_STATUS_INVALID

    def test_custom_policy_denial_carries_typed_reason(self):
        svc = _make_service(policy=_AlwaysDenyPolicy(ReservationRejectionReason.TRADING_HALTED))
        uow = _StubUow()
        with pytest.raises(ReservationDenied) as exc_info:
            svc.reserve(_make_quote(), _ITEM_ID, uow, now=_NOW)
        assert exc_info.value.reason == ReservationRejectionReason.TRADING_HALTED

    def test_denial_does_not_call_repository(self):
        svc = _make_service(policy=_AlwaysDenyPolicy())
        uow = _StubUow()
        with pytest.raises(ReservationDenied):
            svc.reserve(_make_quote(), _ITEM_ID, uow, now=_NOW)
        assert len(uow.repository.locked) == 0
        assert len(uow.repository.saved) == 0

    def test_denial_does_not_enqueue_event(self):
        svc = _make_service(policy=_AlwaysDenyPolicy())
        uow = _StubUow()
        with pytest.raises(ReservationDenied):
            svc.reserve(_make_quote(), _ITEM_ID, uow, now=_NOW)
        assert len(uow.outbox.events) == 0


# ---------------------------------------------------------------------------
# Transaction boundary (UoW)
# ---------------------------------------------------------------------------

class TestTransactionBoundary:
    def test_caller_controls_commit(self):
        svc = _make_service()
        uow = _StubUow()
        svc.reserve(_make_quote(), _ITEM_ID, uow, now=_NOW)
        assert not uow.committed  # service does NOT commit

    def test_caller_can_commit_after_reserve(self):
        svc = _make_service()
        uow = _StubUow()
        with uow:
            svc.reserve(_make_quote(), _ITEM_ID, uow, now=_NOW)  # tuple return, not unpacked
            uow.commit()
        assert uow.committed

    def test_item_already_reserved_propagates_before_save(self):
        svc = _make_service()
        repo = _StubRepository(should_fail_lock=True)
        uow = _StubUow(repository=repo)
        from yasargold_domain.reservation.exceptions import ItemAlreadyReservedException
        with pytest.raises(ItemAlreadyReservedException):
            svc.reserve(_make_quote(), _ITEM_ID, uow, now=_NOW)
        assert len(uow.repository.saved) == 0
        assert len(uow.outbox.events) == 0


# ---------------------------------------------------------------------------
# customer_phone (Sprint 6 — Notifications)
# ---------------------------------------------------------------------------

class TestCustomerPhone:
    def test_customer_phone_stored_in_record(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        svc.reserve(_make_quote(), _ITEM_ID, uow, now=_NOW, customer_phone="+966501234567")
        assert uow.repository.saved[0].customer_phone == "+966501234567"

    def test_customer_phone_none_by_default(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        svc.reserve(_make_quote(), _ITEM_ID, uow, now=_NOW)
        assert uow.repository.saved[0].customer_phone is None

    def test_customer_phone_does_not_affect_locking(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        svc.reserve(_make_quote(), _ITEM_ID, uow, now=_NOW, customer_phone="+966509999999")
        assert len(uow.repository.locked) == 1
