"""Unit tests for the Order aggregate state machine."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from yasargold_domain.orders.order import Order, OrderStatus
from yasargold_domain.shared.identifiers import (
    ItemId,
    OrderId,
    PaymentIntentId,
    ReservationId,
)

_NOW = datetime(2026, 7, 13, 14, 0, 0, tzinfo=timezone.utc)
_ORDER_ID = OrderId("ord_test000000000000001")
_RES_ID = ReservationId("res_test_001")
_PI_ID = PaymentIntentId("pi_test_001")
_ITEM_ID = ItemId(42)


def _order(status: OrderStatus = OrderStatus.CONFIRMED, **kwargs) -> Order:
    return Order(
        id=_ORDER_ID,
        reservation_id=_RES_ID,
        payment_intent_id=_PI_ID,
        item_id=_ITEM_ID,
        amount=Decimal("5500.00"),
        currency="SAR",
        status=status,
        created_at=_NOW,
        confirmed_at=_NOW if status != OrderStatus.PENDING else None,
        **kwargs,
    )


class TestOrderStatusIsTerminal:
    def test_delivered_is_terminal(self) -> None:
        assert _order(OrderStatus.DELIVERED).is_terminal

    def test_cancelled_is_terminal(self) -> None:
        assert _order(OrderStatus.CANCELLED).is_terminal

    def test_confirmed_is_not_terminal(self) -> None:
        assert not _order(OrderStatus.CONFIRMED).is_terminal

    def test_pending_is_not_terminal(self) -> None:
        assert not _order(OrderStatus.PENDING).is_terminal

    def test_ready_is_not_terminal(self) -> None:
        assert not _order(OrderStatus.READY_FOR_SHIPMENT).is_terminal

    def test_shipped_is_not_terminal(self) -> None:
        assert not _order(OrderStatus.SHIPPED).is_terminal


class TestCanShip:
    def test_confirmed_can_ship(self) -> None:
        assert _order(OrderStatus.CONFIRMED).can_ship()

    def test_pending_cannot_ship(self) -> None:
        assert not _order(OrderStatus.PENDING).can_ship()

    def test_ready_cannot_ship(self) -> None:
        assert not _order(OrderStatus.READY_FOR_SHIPMENT).can_ship()

    def test_shipped_cannot_ship(self) -> None:
        assert not _order(OrderStatus.SHIPPED).can_ship()

    def test_delivered_cannot_ship(self) -> None:
        assert not _order(OrderStatus.DELIVERED).can_ship()

    def test_cancelled_cannot_ship(self) -> None:
        assert not _order(OrderStatus.CANCELLED).can_ship()


class TestCanMarkReady:
    def test_confirmed_can_mark_ready(self) -> None:
        assert _order(OrderStatus.CONFIRMED).can_mark_ready()

    def test_shipped_cannot_mark_ready(self) -> None:
        assert not _order(OrderStatus.SHIPPED).can_mark_ready()


class TestCanDeliver:
    def test_shipped_can_deliver(self) -> None:
        assert _order(OrderStatus.SHIPPED).can_deliver()

    def test_confirmed_cannot_deliver(self) -> None:
        assert not _order(OrderStatus.CONFIRMED).can_deliver()

    def test_delivered_cannot_deliver(self) -> None:
        assert not _order(OrderStatus.DELIVERED).can_deliver()


class TestCanCancel:
    def test_confirmed_can_cancel(self) -> None:
        assert _order(OrderStatus.CONFIRMED).can_cancel()

    def test_pending_can_cancel(self) -> None:
        assert _order(OrderStatus.PENDING).can_cancel()

    def test_ready_can_cancel(self) -> None:
        assert _order(OrderStatus.READY_FOR_SHIPMENT).can_cancel()

    def test_shipped_can_cancel(self) -> None:
        assert _order(OrderStatus.SHIPPED).can_cancel()

    def test_delivered_cannot_cancel(self) -> None:
        assert not _order(OrderStatus.DELIVERED).can_cancel()

    def test_already_cancelled_cannot_cancel(self) -> None:
        assert not _order(OrderStatus.CANCELLED).can_cancel()


class TestOrderImmutability:
    def test_order_is_frozen(self) -> None:
        o = _order()
        with pytest.raises(Exception):
            o.status = OrderStatus.CANCELLED  # type: ignore[misc]

    def test_replace_returns_new_instance(self) -> None:
        from dataclasses import replace
        o = _order()
        o2 = replace(o, status=OrderStatus.SHIPPED)
        assert o.status == OrderStatus.CONFIRMED
        assert o2.status == OrderStatus.SHIPPED
        assert o is not o2
