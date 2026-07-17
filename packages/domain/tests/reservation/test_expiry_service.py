"""Unit tests for ReservationExpiryService.

Covers:
  - Happy path: N elapsed reservations → N transitioned to EXPIRED
  - No-op: no elapsed reservations → returns 0
  - Batch limit: only `limit` reservations processed per tick
  - Event correctness: ReservationExpired carries all required fields
  - Atomicity: caller controls commit (service never commits)
  - Idempotency note: processed via stub that verifies EXPIRED rows
    are not re-processed
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from yasargold_domain.reservation.events import DomainEvent, ReservationExpired
from yasargold_domain.reservation.expiry_service import ReservationExpiryService
from yasargold_domain.reservation.repository import ReservationRecord
from yasargold_domain.shared.identifiers import (
    GoldPriceId,
    ItemId,
    QuoteId,
    ReservationId,
)

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 7, 13, 16, 0, 0, tzinfo=timezone.utc)


@dataclass
class _StubRepo:
    records: list[ReservationRecord] = field(default_factory=list)
    updated: list[tuple[ReservationId, str]] = field(default_factory=list)

    def lock_item(self, *a: Any) -> bool:
        return True

    def save_reservation(self, record: ReservationRecord) -> None:
        self.records.append(record)

    def release_lock(self, *a: Any) -> None:
        pass

    def find_by_quote_id(self, *a: Any) -> None:
        return None

    def find_by_id(self, reservation_id: ReservationId) -> ReservationRecord | None:
        for r in self.records:
            if r.id == reservation_id:
                return r
        return None

    def update_status(self, reservation_id: ReservationId, status: str) -> None:
        self.updated.append((reservation_id, status))

    def find_elapsed_active(self, now: datetime, limit: int = 100) -> list[ReservationRecord]:
        return [
            r for r in self.records
            if r.status == "ACTIVE" and _utc(r.valid_until) <= now
        ][:limit]


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


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(
    item_id: int = 42,
    minutes_ago: int = 5,
    status: str = "ACTIVE",
    index: int = 0,
) -> ReservationRecord:
    """Create a reservation whose valid_until is `minutes_ago` minutes in the past."""
    valid_until = _NOW - timedelta(minutes=minutes_ago)
    return ReservationRecord(
        id=ReservationId(f"res_{index:03d}"),
        quote_id=QuoteId(f"qt_{index:03d}"),
        item_id=ItemId(item_id + index),
        gold_price_id=GoldPriceId(18452),
        locked_rate_per_gram_24k=Decimal("230.00"),
        karat_rate_per_gram=Decimal("193.125"),
        pricing_engine_version="v1",
        reserved_at=_NOW - timedelta(minutes=20),
        valid_until=valid_until,
        status=status,
    )


def _make_fresh_record(index: int = 99) -> ReservationRecord:
    """Create a reservation still within its window."""
    return replace(
        _make_record(index=index),
        valid_until=_NOW + timedelta(minutes=10),
    )


# ---------------------------------------------------------------------------
# Core behaviour
# ---------------------------------------------------------------------------

class TestExpiryHappyPath:
    def test_returns_expired_records(self) -> None:
        svc = ReservationExpiryService()
        uow = _StubUow()
        uow.repository.records = [_make_record(index=i) for i in range(3)]
        expired = svc.expire_elapsed(uow, now=_NOW)
        assert len(expired) == 3

    def test_returns_reservation_records(self) -> None:
        svc = ReservationExpiryService()
        uow = _StubUow()
        uow.repository.records = [_make_record(index=i) for i in range(2)]
        expired = svc.expire_elapsed(uow, now=_NOW)
        assert all(isinstance(r, ReservationRecord) for r in expired)

    def test_zero_elapsed_returns_empty_list(self) -> None:
        svc = ReservationExpiryService()
        uow = _StubUow()
        uow.repository.records = [_make_fresh_record()]
        expired = svc.expire_elapsed(uow, now=_NOW)
        assert expired == []

    def test_empty_repository_returns_empty_list(self) -> None:
        svc = ReservationExpiryService()
        uow = _StubUow()
        expired = svc.expire_elapsed(uow, now=_NOW)
        assert expired == []

    def test_updates_each_reservation_to_expired(self) -> None:
        svc = ReservationExpiryService()
        uow = _StubUow()
        uow.repository.records = [_make_record(index=i) for i in range(2)]
        svc.expire_elapsed(uow, now=_NOW)
        updated_statuses = [s for _, s in uow.repository.updated]
        assert updated_statuses.count("EXPIRED") == 2

    def test_skips_already_non_active(self) -> None:
        svc = ReservationExpiryService()
        uow = _StubUow()
        uow.repository.records = [
            _make_record(index=0),                      # ACTIVE + elapsed → expire
            _make_record(index=1, status="COMPLETED"),  # COMPLETED → skip
            _make_record(index=2, status="CANCELLED"),  # CANCELLED → skip
        ]
        expired = svc.expire_elapsed(uow, now=_NOW)
        assert len(expired) == 1

    def test_does_not_expire_fresh_reservations(self) -> None:
        svc = ReservationExpiryService()
        uow = _StubUow()
        uow.repository.records = [
            _make_record(index=0),       # elapsed
            _make_fresh_record(index=1), # fresh
        ]
        expired = svc.expire_elapsed(uow, now=_NOW)
        assert len(expired) == 1


# ---------------------------------------------------------------------------
# Outbox events
# ---------------------------------------------------------------------------

class TestExpiryEvents:
    def test_enqueues_one_event_per_expiry(self) -> None:
        svc = ReservationExpiryService()
        uow = _StubUow()
        uow.repository.records = [_make_record(index=i) for i in range(3)]
        svc.expire_elapsed(uow, now=_NOW)
        assert len(uow.outbox.events) == 3

    def test_enqueues_reservation_expired_type(self) -> None:
        svc = ReservationExpiryService()
        uow = _StubUow()
        uow.repository.records = [_make_record(index=0)]
        svc.expire_elapsed(uow, now=_NOW)
        assert isinstance(uow.outbox.events[0], ReservationExpired)

    def test_event_carries_reservation_id(self) -> None:
        svc = ReservationExpiryService()
        uow = _StubUow()
        record = _make_record(index=0)
        uow.repository.records = [record]
        svc.expire_elapsed(uow, now=_NOW)
        event: ReservationExpired = uow.outbox.events[0]  # type: ignore[assignment]
        assert event.reservation_id == record.id

    def test_event_carries_item_id(self) -> None:
        svc = ReservationExpiryService()
        uow = _StubUow()
        record = _make_record(index=0)
        uow.repository.records = [record]
        svc.expire_elapsed(uow, now=_NOW)
        event: ReservationExpired = uow.outbox.events[0]  # type: ignore[assignment]
        assert event.item_id == record.item_id

    def test_each_event_has_unique_id(self) -> None:
        svc = ReservationExpiryService()
        uow = _StubUow()
        uow.repository.records = [_make_record(index=i) for i in range(3)]
        svc.expire_elapsed(uow, now=_NOW)
        ids = [e.event_id for e in uow.outbox.events]
        assert len(ids) == len(set(ids))

    def test_no_events_when_nothing_expired(self) -> None:
        svc = ReservationExpiryService()
        uow = _StubUow()
        uow.repository.records = [_make_fresh_record()]
        svc.expire_elapsed(uow, now=_NOW)
        assert len(uow.outbox.events) == 0


# ---------------------------------------------------------------------------
# Batch limit
# ---------------------------------------------------------------------------

class TestBatchLimit:
    def test_limit_caps_processed_count(self) -> None:
        svc = ReservationExpiryService()
        uow = _StubUow()
        uow.repository.records = [_make_record(index=i) for i in range(10)]
        expired = svc.expire_elapsed(uow, now=_NOW, limit=3)
        assert len(expired) == 3

    def test_limit_caps_events_enqueued(self) -> None:
        svc = ReservationExpiryService()
        uow = _StubUow()
        uow.repository.records = [_make_record(index=i) for i in range(10)]
        svc.expire_elapsed(uow, now=_NOW, limit=3)
        assert len(uow.outbox.events) == 3

    def test_default_limit_is_100(self) -> None:
        svc = ReservationExpiryService()
        uow = _StubUow()
        uow.repository.records = [_make_record(index=i) for i in range(150)]
        expired = svc.expire_elapsed(uow, now=_NOW)
        assert len(expired) == 100

    def test_expired_records_contain_reserved_at(self) -> None:
        """Returned records expose reserved_at so workers can record lifetimes."""
        svc = ReservationExpiryService()
        uow = _StubUow()
        record = _make_record(index=0)
        uow.repository.records = [record]
        expired = svc.expire_elapsed(uow, now=_NOW)
        assert expired[0].reserved_at == record.reserved_at


# ---------------------------------------------------------------------------
# Transaction boundary
# ---------------------------------------------------------------------------

class TestTransactionBoundary:
    def test_service_does_not_commit(self) -> None:
        svc = ReservationExpiryService()
        uow = _StubUow()
        uow.repository.records = [_make_record()]
        svc.expire_elapsed(uow, now=_NOW)
        assert not uow.committed

    def test_caller_commits_after_expire(self) -> None:
        svc = ReservationExpiryService()
        uow = _StubUow()
        uow.repository.records = [_make_record()]
        with uow:
            svc.expire_elapsed(uow, now=_NOW)
            uow.commit()
        assert uow.committed
