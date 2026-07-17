"""Unit tests for CheckoutService.

CheckoutService now creates an Order AND completes a Reservation atomically.
The UoW is CheckoutUnitOfWork (has both reservation_repository and order repo).

Scenarios:
  1. Happy path:     ACTIVE reservation + payment confirmed → Order(CONFIRMED) + Reservation(COMPLETED)
  2. Expiry:         valid_until elapsed → ReservationExpiredError, no Order created
  3. Wrong status:   already COMPLETED/CANCELLED → ReservationStatusError, no Order created
  4. Not found:      unknown reservation_id → ReservationNotFoundException
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from yasargold_domain.orders.events import OrderCreated
from yasargold_domain.orders.order import OrderStatus
from yasargold_domain.orders.testing import FakeCheckoutUnitOfWork
from yasargold_domain.reservation.checkout_service import CheckoutService
from yasargold_domain.reservation.events import ReservationConfirmed
from yasargold_domain.reservation.exceptions import (
    ReservationExpiredError,
    ReservationNotFoundException,
    ReservationStatusError,
)
from yasargold_domain.reservation.repository import ReservationRecord
from yasargold_domain.shared.identifiers import (
    GoldPriceId,
    ItemId,
    PaymentIntentId,
    QuoteId,
    ReservationId,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 7, 13, 14, 0, 0, tzinfo=timezone.utc)
_RES_ID = ReservationId("res_abc123")
_QUOTE_ID = QuoteId("qt_xyz456")
_ITEM_ID = ItemId(42)
_PI_ID = PaymentIntentId("pi_test_abc123")
_AMOUNT = Decimal("5500.00")
_CURRENCY = "SAR"


def _make_record(
    status: str = "ACTIVE",
    minutes_until_expiry: int = 10,
) -> ReservationRecord:
    return ReservationRecord(
        id=_RES_ID,
        quote_id=_QUOTE_ID,
        item_id=_ITEM_ID,
        gold_price_id=GoldPriceId(18452),
        locked_rate_per_gram_24k=Decimal("230.00"),
        karat_rate_per_gram=Decimal("193.125"),
        pricing_engine_version="v1",
        reserved_at=_NOW - timedelta(minutes=5),
        valid_until=_NOW + timedelta(minutes=minutes_until_expiry),
        status=status,
    )


def _make_uow(record: ReservationRecord | None = None) -> FakeCheckoutUnitOfWork:
    uow = FakeCheckoutUnitOfWork()
    if record is not None:
        uow.reservation_repository.records[str(record.id)] = record
    return uow


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestConfirmHappyPath:
    def test_returns_completed_reservation(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record())
        reservation, _ = svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)
        assert reservation.status == "COMPLETED"

    def test_returns_confirmed_order(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record())
        _, order = svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)
        assert order.status == OrderStatus.CONFIRMED

    def test_order_linked_to_reservation(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record())
        _, order = svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)
        assert order.reservation_id == _RES_ID

    def test_updates_reservation_status_in_repo(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record())
        svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)
        assert (_RES_ID, "COMPLETED") in uow.reservation_repository.updated

    def test_enqueues_order_created_event(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record())
        svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)
        assert any(isinstance(e, OrderCreated) for e in uow.outbox.events)

    def test_enqueues_reservation_confirmed_event(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record())
        svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)
        assert any(isinstance(e, ReservationConfirmed) for e in uow.outbox.events)

    def test_reservation_confirmed_carries_payment_intent_id(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record())
        svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)
        events = [e for e in uow.outbox.events if isinstance(e, ReservationConfirmed)]
        assert events[0].payment_intent_id == _PI_ID

    def test_caller_controls_commit(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record())
        svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)
        assert not uow.committed


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------

class TestWebhookAfterExpiry:
    def test_expired_raises_error(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record(minutes_until_expiry=-1))
        with pytest.raises(ReservationExpiredError):
            svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)

    def test_expired_creates_no_order(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record(minutes_until_expiry=-1))
        with pytest.raises(ReservationExpiredError):
            svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)
        assert uow.repository.find_by_reservation_id(_RES_ID) is None

    def test_expired_does_not_update_reservation(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record(minutes_until_expiry=-1))
        with pytest.raises(ReservationExpiredError):
            svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)
        assert len(uow.reservation_repository.updated) == 0

    def test_expired_enqueues_no_events(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record(minutes_until_expiry=-1))
        with pytest.raises(ReservationExpiredError):
            svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)
        assert len(uow.outbox.events) == 0

    def test_exactly_at_expiry_is_rejected(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record(minutes_until_expiry=0))
        with pytest.raises(ReservationExpiredError):
            svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)

    def test_one_second_before_expiry_succeeds(self) -> None:
        from dataclasses import replace
        svc = CheckoutService()
        record = replace(_make_record(), valid_until=_NOW + timedelta(seconds=1))
        uow = _make_uow(record)
        reservation, _ = svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)
        assert reservation.status == "COMPLETED"


# ---------------------------------------------------------------------------
# Wrong status
# ---------------------------------------------------------------------------

class TestStatusErrors:
    def test_already_completed_raises_status_error(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record(status="COMPLETED"))
        with pytest.raises(ReservationStatusError) as exc_info:
            svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)
        assert exc_info.value.current_status == "COMPLETED"

    def test_cancelled_raises_status_error(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record(status="CANCELLED"))
        with pytest.raises(ReservationStatusError):
            svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)

    def test_status_error_enqueues_no_events(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record(status="CANCELLED"))
        with pytest.raises(ReservationStatusError):
            svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)
        assert len(uow.outbox.events) == 0


# ---------------------------------------------------------------------------
# Not found
# ---------------------------------------------------------------------------

class TestNotFound:
    def test_unknown_id_raises_not_found(self) -> None:
        svc = CheckoutService()
        uow = _make_uow()
        with pytest.raises(ReservationNotFoundException):
            svc.confirm(ReservationId("res_unknown"), _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)
