"""BOLA tests for OrderService — Law 5 runtime enforcement (ADR-017).

Mirrors the pattern in packages/domain/tests/reservation/test_bola.py.

find_order_for_customer(order_id, customer_ref, uow) must:
    - Return the Order when customer_ref matches order.customer_ref
    - Return None when customer_ref does not match (BOLA — no 403 oracle)
    - Return None when customer_ref is None (unauthenticated — deny by default)
    - Return None when the order does not exist
    - Never raise on wrong ownership (caller maps None → 404)
    - Pre-v1.4 orders (customer_ref=None) are inaccessible to any caller
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from yasargold_domain.orders.order import Order, OrderStatus
from yasargold_domain.orders.service import OrderService
from yasargold_domain.shared.identifiers import (
    ItemId,
    OrderId,
    PaymentIntentId,
    ReservationId,
)


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

@dataclass
class _StubOrderRepository:
    _order: Order | None = None

    def find_by_id(self, order_id: OrderId) -> Order | None:
        if self._order and self._order.id == order_id:
            return self._order
        return None

    def save(self, order: Order) -> None:
        self._order = order

    def find_by_reservation_id(self, reservation_id: ReservationId) -> Order | None:
        return None


@dataclass
class _StubOutbox:
    def enqueue(self, event: object) -> None:
        pass


@dataclass
class _StubUoW:
    repository: _StubOrderRepository
    outbox: _StubOutbox = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.outbox is None:
            self.outbox = _StubOutbox()


_NOW = datetime(2026, 7, 14, 10, 0, 0, tzinfo=timezone.utc)
_ORDER_ID = OrderId("ord_bola_test_001")
_OWNER_REF = "+966500000001"
_OTHER_REF = "+966500000002"


def _make_order(customer_ref: str | None = _OWNER_REF) -> Order:
    return Order(
        id=_ORDER_ID,
        reservation_id=ReservationId("res_bola_001"),
        payment_intent_id=PaymentIntentId("pi_bola_001"),
        item_id=ItemId(42),
        amount=Decimal("5500.00"),
        currency="SAR",
        status=OrderStatus.CONFIRMED,
        created_at=_NOW,
        confirmed_at=_NOW,
        customer_ref=customer_ref,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOrderBOLA:
    def setup_method(self) -> None:
        self._service = OrderService()

    def _uow(self, order: Order | None) -> _StubUoW:
        repo = _StubOrderRepository(_order=order)
        return _StubUoW(repository=repo)

    def test_owner_can_fetch_own_order(self) -> None:
        order = _make_order(customer_ref=_OWNER_REF)
        result = self._service.find_order_for_customer(_ORDER_ID, _OWNER_REF, self._uow(order))
        assert result is not None
        assert result.id == _ORDER_ID

    def test_non_owner_gets_none(self) -> None:
        order = _make_order(customer_ref=_OWNER_REF)
        result = self._service.find_order_for_customer(_ORDER_ID, _OTHER_REF, self._uow(order))
        assert result is None

    def test_unauthenticated_gets_none(self) -> None:
        order = _make_order(customer_ref=_OWNER_REF)
        result = self._service.find_order_for_customer(_ORDER_ID, None, self._uow(order))
        assert result is None

    def test_nonexistent_order_returns_none(self) -> None:
        result = self._service.find_order_for_customer(
            OrderId("ord_does_not_exist"), _OWNER_REF, self._uow(None)
        )
        assert result is None

    def test_no_raise_on_wrong_owner(self) -> None:
        order = _make_order(customer_ref=_OWNER_REF)
        try:
            self._service.find_order_for_customer(_ORDER_ID, _OTHER_REF, self._uow(order))
        except Exception as exc:
            pytest.fail(f"find_order_for_customer must not raise on wrong owner: {exc}")

    def test_pre_v14_order_inaccessible(self) -> None:
        """Orders created before v1.4 have customer_ref=None — no caller can read them."""
        order = _make_order(customer_ref=None)
        result = self._service.find_order_for_customer(_ORDER_ID, _OWNER_REF, self._uow(order))
        assert result is None, "Pre-v1.4 orders (customer_ref=None) must not be accessible"

    def test_customer_ref_exact_match_required(self) -> None:
        """Prefix/substring match is not sufficient — must be exact."""
        order = _make_order(customer_ref="+966500000001")
        result = self._service.find_order_for_customer(_ORDER_ID, "+96650000000", self._uow(order))
        assert result is None
