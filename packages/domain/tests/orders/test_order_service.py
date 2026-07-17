"""Unit tests for OrderService."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from yasargold_domain.orders.events import OrderCancelled, OrderCreated
from yasargold_domain.orders.exceptions import OrderNotFoundException, OrderStatusError
from yasargold_domain.orders.order import OrderStatus
from yasargold_domain.orders.service import OrderService
from yasargold_domain.orders.testing import FakeOrderUnitOfWork
from yasargold_domain.shared.identifiers import (
    ItemId,
    PaymentIntentId,
    ReservationId,
)

_NOW = datetime(2026, 7, 13, 14, 0, 0, tzinfo=timezone.utc)
_RES_ID = ReservationId("res_test_001")
_PI_ID = PaymentIntentId("pi_test_001")
_ITEM_ID = ItemId(42)
_AMOUNT = Decimal("5500.00")
_CURRENCY = "SAR"


def _create_order(uow: FakeOrderUnitOfWork | None = None) -> tuple:
    svc = OrderService()
    uow = uow or FakeOrderUnitOfWork()
    order = svc.create_from_reservation(
        reservation_id=_RES_ID,
        item_id=_ITEM_ID,
        payment_intent_id=_PI_ID,
        amount=_AMOUNT,
        currency=_CURRENCY,
        uow=uow,
        now=_NOW,
    )
    return order, uow


class TestCreateFromReservation:
    def test_creates_order_with_confirmed_status(self) -> None:
        order, _ = _create_order()
        assert order.status == OrderStatus.CONFIRMED

    def test_order_id_starts_with_ord(self) -> None:
        order, _ = _create_order()
        assert str(order.id).startswith("ord_")

    def test_order_carries_reservation_id(self) -> None:
        order, _ = _create_order()
        assert order.reservation_id == _RES_ID

    def test_order_carries_payment_intent_id(self) -> None:
        order, _ = _create_order()
        assert order.payment_intent_id == _PI_ID

    def test_order_carries_item_id(self) -> None:
        order, _ = _create_order()
        assert order.item_id == _ITEM_ID

    def test_order_carries_amount(self) -> None:
        order, _ = _create_order()
        assert order.amount == _AMOUNT

    def test_order_carries_currency(self) -> None:
        order, _ = _create_order()
        assert order.currency == _CURRENCY

    def test_confirmed_at_set_to_now(self) -> None:
        order, _ = _create_order()
        assert order.confirmed_at == _NOW

    def test_order_saved_to_repository(self) -> None:
        order, uow = _create_order()
        assert uow.repository.find_by_id(order.id) is not None

    def test_order_findable_by_reservation_id(self) -> None:
        order, uow = _create_order()
        found = uow.repository.find_by_reservation_id(_RES_ID)
        assert found is not None
        assert found.id == order.id

    def test_enqueues_order_created_event(self) -> None:
        _, uow = _create_order()
        assert len(uow.outbox.events) == 1
        assert isinstance(uow.outbox.events[0], OrderCreated)

    def test_event_carries_order_id(self) -> None:
        order, uow = _create_order()
        event: OrderCreated = uow.outbox.events[0]  # type: ignore[assignment]
        assert event.order_id == order.id

    def test_event_carries_reservation_id(self) -> None:
        _, uow = _create_order()
        event: OrderCreated = uow.outbox.events[0]  # type: ignore[assignment]
        assert event.reservation_id == _RES_ID

    def test_event_carries_item_id(self) -> None:
        _, uow = _create_order()
        event: OrderCreated = uow.outbox.events[0]  # type: ignore[assignment]
        assert event.item_id == _ITEM_ID

    def test_event_carries_amount(self) -> None:
        _, uow = _create_order()
        event: OrderCreated = uow.outbox.events[0]  # type: ignore[assignment]
        assert event.amount == _AMOUNT

    def test_two_calls_produce_unique_ids(self) -> None:
        svc = OrderService()
        uow1, uow2 = FakeOrderUnitOfWork(), FakeOrderUnitOfWork()
        o1 = svc.create_from_reservation(_RES_ID, _ITEM_ID, _PI_ID, _AMOUNT, _CURRENCY, uow1, now=_NOW)
        o2 = svc.create_from_reservation(_RES_ID, _ITEM_ID, _PI_ID, _AMOUNT, _CURRENCY, uow2, now=_NOW)
        assert o1.id != o2.id

    def test_service_does_not_commit(self) -> None:
        _, uow = _create_order()
        assert not uow.committed


class TestCancel:
    def test_cancels_confirmed_order(self) -> None:
        svc = OrderService()
        uow = FakeOrderUnitOfWork()
        order, _ = _create_order(uow)
        cancelled = svc.cancel(order.id, "customer_request", uow, now=_NOW)
        assert cancelled.status == OrderStatus.CANCELLED

    def test_sets_cancellation_reason(self) -> None:
        svc = OrderService()
        uow = FakeOrderUnitOfWork()
        order, _ = _create_order(uow)
        cancelled = svc.cancel(order.id, "fraud", uow, now=_NOW)
        assert cancelled.cancellation_reason == "fraud"

    def test_enqueues_order_cancelled_event(self) -> None:
        svc = OrderService()
        uow = FakeOrderUnitOfWork()
        order, _ = _create_order(uow)
        svc.cancel(order.id, "customer_request", uow, now=_NOW)
        assert any(isinstance(e, OrderCancelled) for e in uow.outbox.events)

    def test_raises_not_found_for_unknown_id(self) -> None:
        from yasargold_domain.shared.identifiers import OrderId
        svc = OrderService()
        uow = FakeOrderUnitOfWork()
        with pytest.raises(OrderNotFoundException):
            svc.cancel(OrderId("ord_unknown"), "test", uow, now=_NOW)

    def test_raises_status_error_for_delivered_order(self) -> None:
        from dataclasses import replace
        svc = OrderService()
        uow = FakeOrderUnitOfWork()
        order, _ = _create_order(uow)
        delivered = replace(order, status=OrderStatus.DELIVERED)
        uow.repository.save(delivered)
        with pytest.raises(OrderStatusError):
            svc.cancel(order.id, "too_late", uow, now=_NOW)

    def test_raises_status_error_for_already_cancelled(self) -> None:
        from dataclasses import replace
        svc = OrderService()
        uow = FakeOrderUnitOfWork()
        order, _ = _create_order(uow)
        already = replace(order, status=OrderStatus.CANCELLED)
        uow.repository.save(already)
        with pytest.raises(OrderStatusError):
            svc.cancel(order.id, "duplicate", uow, now=_NOW)
