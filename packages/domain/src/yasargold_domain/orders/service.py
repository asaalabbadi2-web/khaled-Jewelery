"""OrderService — creates and transitions Order aggregates.

Stateless. Safe to instantiate once and share across requests.

create_from_reservation() is the primary entry point. It is called by
CheckoutService.confirm() as part of the atomic checkout transaction.
ship() and deliver() are called by the Shipping router (Sprint 7).
cancel() is called by cancellation flows.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from yasargold_domain.orders.events import OrderCancelled, OrderCreated
from yasargold_domain.orders.exceptions import OrderNotFoundException, OrderStatusError
from yasargold_domain.orders.order import Order, OrderStatus
from yasargold_domain.orders.unit_of_work import OrderUnitOfWork
from yasargold_domain.shared.identifiers import (
    ItemId,
    OrderId,
    PaymentIntentId,
    ReservationId,
)


def _new_order_id() -> OrderId:
    return OrderId(f"ord_{uuid.uuid4().hex[:20]}")


class OrderService:
    """Creates and manages Order aggregates.

    Stateless — safe to instantiate once at application startup.
    """

    def find_order_for_customer(
        self,
        order_id: OrderId,
        customer_ref: str | None,
        uow: OrderUnitOfWork,
    ) -> Order | None:
        """Return the Order only if customer_ref matches its owner. Returns None otherwise.

        BOLA (Law 5): ownership check is in the domain service, not in the router.
        The router maps None → 404 (not 403 — 403 reveals the resource exists).

        Rules:
        - customer_ref is None (unauthenticated) → always None (deny by default)
        - order.customer_ref is None (pre-v1.4 record) → always None
        - match → return order
        """
        if customer_ref is None:
            return None
        order = uow.repository.find_by_id(order_id)
        if order is None:
            return None
        if order.customer_ref != customer_ref:
            return None
        return order

    def create_from_reservation(
        self,
        reservation_id: ReservationId,
        item_id: ItemId,
        payment_intent_id: PaymentIntentId,
        amount: Decimal,
        currency: str,
        uow: OrderUnitOfWork,
        now: datetime | None = None,
        customer_ref: str | None = None,
    ) -> Order:
        """Create a CONFIRMED Order from a paid Reservation.

        Called by CheckoutService.confirm() after payment is confirmed.
        The caller (CheckoutService) owns uow.commit().

        The Order starts as CONFIRMED — payment is already received, so there
        is no intervening PENDING state in this flow.

        Raises: nothing — caller guarantees reservation_id is valid at this point.
        """
        t = now or datetime.now(timezone.utc)
        order = Order(
            id=_new_order_id(),
            reservation_id=reservation_id,
            payment_intent_id=payment_intent_id,
            item_id=item_id,
            amount=amount,
            currency=currency,
            status=OrderStatus.CONFIRMED,
            created_at=t,
            confirmed_at=t,
            customer_ref=customer_ref,
        )
        uow.repository.save(order)
        uow.outbox.enqueue(
            OrderCreated(
                order_id=order.id,
                reservation_id=reservation_id,
                payment_intent_id=payment_intent_id,
                item_id=item_id,
                amount=amount,
                currency=currency,
                created_at=t,
            )
        )
        return order

    def cancel(
        self,
        order_id: OrderId,
        reason: str,
        uow: OrderUnitOfWork,
        now: datetime | None = None,
    ) -> Order:
        """Cancel a non-terminal Order.

        Raises:
            OrderNotFoundException: order_id does not exist.
            OrderStatusError:       order is already DELIVERED or CANCELLED.
        """
        t = now or datetime.now(timezone.utc)
        order = uow.repository.find_by_id(order_id)
        if order is None:
            raise OrderNotFoundException(str(order_id))
        if not order.can_cancel():
            raise OrderStatusError(
                str(order_id),
                current_status=order.status.value,
                expected="non-terminal",
            )
        from dataclasses import replace
        cancelled = replace(
            order,
            status=OrderStatus.CANCELLED,
            cancelled_at=t,
            cancellation_reason=reason,
        )
        uow.repository.save(cancelled)
        uow.outbox.enqueue(
            OrderCancelled(
                order_id=order_id,
                reservation_id=order.reservation_id,
                item_id=order.item_id,
                cancellation_reason=reason,
                cancelled_at=t,
            )
        )
        return cancelled

    def ship(
        self,
        order_id: OrderId,
        uow: OrderUnitOfWork,
        now: datetime | None = None,
    ) -> Order:
        """Transition Order CONFIRMED → SHIPPED when a Shipment is registered.

        Called by the Shipping router after ShipmentService.mark_created() succeeds.

        Raises:
            OrderNotFoundException: order_id does not exist.
            OrderStatusError:       order is not in CONFIRMED status.
        """
        t = now or datetime.now(timezone.utc)
        order = uow.repository.find_by_id(order_id)
        if order is None:
            raise OrderNotFoundException(str(order_id))
        if not order.can_ship():
            raise OrderStatusError(
                str(order_id),
                current_status=order.status.value,
                expected="CONFIRMED",
            )
        from dataclasses import replace
        shipped = replace(order, status=OrderStatus.SHIPPED, shipped_at=t)
        uow.repository.save(shipped)
        return shipped

    def deliver(
        self,
        order_id: OrderId,
        uow: OrderUnitOfWork,
        now: datetime | None = None,
    ) -> Order:
        """Transition Order SHIPPED → DELIVERED.

        Triggered by ShipmentDelivered event-of-record (§13: event path, not cache).
        Called by a worker consuming ShipmentDelivered from the Outbox.

        Raises:
            OrderNotFoundException: order_id does not exist.
            OrderStatusError:       order is not in SHIPPED status.
        """
        t = now or datetime.now(timezone.utc)
        order = uow.repository.find_by_id(order_id)
        if order is None:
            raise OrderNotFoundException(str(order_id))
        if not order.can_deliver():
            raise OrderStatusError(
                str(order_id),
                current_status=order.status.value,
                expected="SHIPPED",
            )
        from dataclasses import replace
        delivered = replace(order, status=OrderStatus.DELIVERED, delivered_at=t)
        uow.repository.save(delivered)
        return delivered
