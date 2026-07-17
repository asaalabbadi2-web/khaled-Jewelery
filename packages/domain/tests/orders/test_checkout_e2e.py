"""E2E tests for the CheckoutService → OrderService chain.

Tests the full atomic checkout flow with in-memory stubs.
No DB, no HTTP, no external dependencies.
"""
from __future__ import annotations

from dataclasses import replace
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

_NOW = datetime(2026, 7, 13, 14, 0, 0, tzinfo=timezone.utc)
_RES_ID = ReservationId("res_checkout_e2e_001")
_QUOTE_ID = QuoteId("qt_checkout_e2e_001")
_ITEM_ID = ItemId(42)
_PI_ID = PaymentIntentId("pi_checkout_e2e_001")
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


class TestHappyPath:
    def test_returns_completed_reservation_and_order(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record())
        reservation, order = svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)
        assert reservation.status == "COMPLETED"
        assert order.status == OrderStatus.CONFIRMED

    def test_order_linked_to_reservation(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record())
        _, order = svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)
        assert order.reservation_id == _RES_ID

    def test_order_carries_payment_intent_id(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record())
        _, order = svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)
        assert order.payment_intent_id == _PI_ID

    def test_reservation_updated_to_completed_in_repo(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record())
        svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)
        assert (_RES_ID, "COMPLETED") in [
            (rid, s) for rid, s in uow.reservation_repository.updated
        ]

    def test_enqueues_order_created_and_reservation_confirmed(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record())
        svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)
        types = {type(e) for e in uow.outbox.events}
        assert OrderCreated in types
        assert ReservationConfirmed in types

    def test_exactly_two_events_enqueued(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record())
        svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)
        assert len(uow.outbox.events) == 2

    def test_reservation_confirmed_carries_payment_intent_id(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record())
        svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)
        events = [e for e in uow.outbox.events if isinstance(e, ReservationConfirmed)]
        assert events[0].payment_intent_id == _PI_ID

    def test_service_does_not_commit(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record())
        svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)
        assert not uow.committed

    def test_caller_commits_after_confirm(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record())
        with uow:
            svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)
            uow.commit()
        assert uow.committed


class TestExpiredReservation:
    def test_expired_raises_error(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record(minutes_until_expiry=-1))
        with pytest.raises(ReservationExpiredError):
            svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)

    def test_expired_enqueues_no_events(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record(minutes_until_expiry=-1))
        with pytest.raises(ReservationExpiredError):
            svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)
        assert len(uow.outbox.events) == 0

    def test_expired_does_not_update_reservation(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record(minutes_until_expiry=-1))
        with pytest.raises(ReservationExpiredError):
            svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)
        assert len(uow.reservation_repository.updated) == 0

    def test_expired_creates_no_order(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record(minutes_until_expiry=-1))
        with pytest.raises(ReservationExpiredError):
            svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)
        assert uow.repository.find_by_reservation_id(_RES_ID) is None


class TestStatusErrors:
    def test_already_completed_raises_status_error(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record(status="COMPLETED"))
        with pytest.raises(ReservationStatusError):
            svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)

    def test_cancelled_raises_status_error(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record(status="CANCELLED"))
        with pytest.raises(ReservationStatusError):
            svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)

    def test_status_error_creates_no_order(self) -> None:
        svc = CheckoutService()
        uow = _make_uow(_make_record(status="COMPLETED"))
        with pytest.raises(ReservationStatusError):
            svc.confirm(_RES_ID, _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)
        assert uow.repository.find_by_reservation_id(_RES_ID) is None


class TestNotFound:
    def test_unknown_reservation_raises_not_found(self) -> None:
        svc = CheckoutService()
        uow = _make_uow()  # empty
        with pytest.raises(ReservationNotFoundException):
            svc.confirm(ReservationId("res_unknown"), _PI_ID, _AMOUNT, _CURRENCY, uow, now=_NOW)
