"""Law 5 — BOLA: ownership check lives in the domain service (ADR-017).

BOLA (Broken Object Level Authorization) is the #1 API security risk in
commerce contexts: a customer changes an ID in the URL and reads (or
cancels) another customer's reservation.

The fix does NOT live in the router:
    ✗  if reservation.customer_phone != request.customer_phone: raise 403
    ✓  service.find_reservation_for_customer(id, customer_ref, uow) → None

The router maps None → 404. It never returns 403 — confirming a resource
exists to an unauthorized caller is an oracle attack (lets them enumerate
valid reservation IDs by checking whether they get 403 vs 404).

These tests prove the ownership check holds at the domain service level,
independent of the HTTP stack. The HTTP contract (None → 404) is tested
in the route contract tests.

Timeline:
    v1.3: customer_ref = customer_phone (weak — not verified; establishes pattern)
    v1.4: customer_ref = JWT sub (verified by middleware before domain call)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from yasargold_domain.reservation.repository import ReservationRecord
from yasargold_domain.reservation.service import ReservationService
from yasargold_domain.reservation.unit_of_work import ReservationUnitOfWork
from yasargold_domain.pricing.reservation_policy import CompositePolicy, DefaultQuotePolicy
from yasargold_domain.shared.identifiers import (
    GoldPriceId, ItemId, QuoteId, ReservationId,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 7, 14, 10, 0, 0, tzinfo=timezone.utc)
_RES_ID = ReservationId("res_alice_001")
_ITEM_ID = ItemId(1)
_QUOTE_ID = QuoteId("qt_alice_001")

_ALICE_PHONE = "+966501234567"
_BOB_PHONE = "+966509999999"

_ALICE_RESERVATION = ReservationRecord(
    id=_RES_ID,
    quote_id=_QUOTE_ID,
    item_id=_ITEM_ID,
    gold_price_id=GoldPriceId(1),
    locked_rate_per_gram_24k=Decimal("220.00"),
    karat_rate_per_gram=Decimal("192.50"),
    pricing_engine_version="1.0",
    reserved_at=_NOW,
    valid_until=_NOW,
    status="ACTIVE",
    customer_phone=_ALICE_PHONE,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

@dataclass
class _FakeRepository:
    _record: ReservationRecord | None = None

    def find_by_id(self, reservation_id: ReservationId) -> ReservationRecord | None:
        if self._record and self._record.id == reservation_id:
            return self._record
        return None

    def find_by_quote_id(self, quote_id: QuoteId) -> ReservationRecord | None:
        return None

    def lock_item(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def save_reservation(self, record: ReservationRecord) -> None:
        self._record = record

    def release_lock(self, *args: Any, **kwargs: Any) -> None:
        pass

    def find_active_by_item(self, item_id: ItemId) -> ReservationRecord | None:
        return None

    def find_expired(self, *args: Any, **kwargs: Any) -> list[ReservationRecord]:
        return []

    def update_status(self, *args: Any, **kwargs: Any) -> None:
        pass


@dataclass
class _FakeOutbox:
    events: list = field(default_factory=list)

    def enqueue(self, event: Any) -> None:
        self.events.append(event)


@dataclass
class _FakeUoW:
    repository: _FakeRepository = field(default_factory=_FakeRepository)
    outbox: _FakeOutbox = field(default_factory=_FakeOutbox)

    def __enter__(self) -> _FakeUoW:
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def commit(self) -> None:
        pass


def _service() -> ReservationService:
    return ReservationService(policy=CompositePolicy(policies=[DefaultQuotePolicy()]))


# ---------------------------------------------------------------------------
# Law 5 tests
# ---------------------------------------------------------------------------

class TestBOLAOwnershipCheck:
    def test_owner_can_fetch_own_reservation(self) -> None:
        """Alice can read her own reservation."""
        svc = _service()
        uow = _FakeUoW()
        uow.repository._record = _ALICE_RESERVATION

        result = svc.find_reservation_for_customer(_RES_ID, _ALICE_PHONE, uow)

        assert result is not None
        assert result.id == _RES_ID

    def test_non_owner_gets_none_not_403(self) -> None:
        """Bob cannot read Alice's reservation — service returns None, not an exception.

        The router maps None → 404. Bob cannot tell whether the reservation
        exists or he is unauthorised — no oracle.
        """
        svc = _service()
        uow = _FakeUoW()
        uow.repository._record = _ALICE_RESERVATION

        result = svc.find_reservation_for_customer(_RES_ID, _BOB_PHONE, uow)

        assert result is None

    def test_unauthenticated_caller_gets_none(self) -> None:
        """customer_ref=None (no auth) always returns None — deny by default."""
        svc = _service()
        uow = _FakeUoW()
        uow.repository._record = _ALICE_RESERVATION

        result = svc.find_reservation_for_customer(_RES_ID, None, uow)

        assert result is None

    def test_nonexistent_reservation_returns_none(self) -> None:
        """Missing reservation returns None — same response as unauthorised access.

        A caller cannot distinguish 'does not exist' from 'you don't own it'.
        Both map to 404 at the HTTP layer.
        """
        svc = _service()
        uow = _FakeUoW()  # empty repository — no reservations

        result = svc.find_reservation_for_customer(
            ReservationId("res_nonexistent"), _ALICE_PHONE, uow
        )

        assert result is None

    def test_service_does_not_raise_on_wrong_owner(self) -> None:
        """Ownership mismatch must never raise — raising exposes resource existence."""
        svc = _service()
        uow = _FakeUoW()
        uow.repository._record = _ALICE_RESERVATION

        # Must not raise any exception
        result = svc.find_reservation_for_customer(_RES_ID, _BOB_PHONE, uow)
        assert result is None

    def test_ownership_check_is_exact_match(self) -> None:
        """Prefix or suffix of the correct customer_ref must not grant access."""
        svc = _service()
        uow = _FakeUoW()
        uow.repository._record = _ALICE_RESERVATION

        partial_ref = _ALICE_PHONE[:-1]  # one character shorter
        result = svc.find_reservation_for_customer(_RES_ID, partial_ref, uow)
        assert result is None
