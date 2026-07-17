"""SQLAlchemy implementations of OrderRepository and OrderEventOutbox.

Both operate on the same Session so they participate in the same transaction.
The CheckoutUnitOfWork (checkout_uow.py) holds the session and exposes both.

save() uses INSERT-or-UPDATE semantics: first call inserts, subsequent
calls update (for status transitions like CONFIRMED → SHIPPED).
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from yasargold_commerce.infra.order_orm import OrderRow
from yasargold_commerce.infra.reservation_orm import OutboxEventRow
from yasargold_domain.orders.order import Order, OrderStatus
from yasargold_domain.reservation.events import DomainEvent
from yasargold_domain.shared.identifiers import (
    ItemId,
    OrderId,
    PaymentIntentId,
    ReservationId,
)


def _json_default(obj: object) -> str:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


class SQLAlchemyOrderRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, order: Order) -> None:
        existing = self._session.get(OrderRow, str(order.id))
        if existing is None:
            row = OrderRow(
                id=str(order.id),
                reservation_id=str(order.reservation_id),
                payment_intent_id=str(order.payment_intent_id),
                item_id=int(order.item_id),
                amount=str(order.amount),
                currency=order.currency,
                status=order.status.value,
                created_at=order.created_at,
                confirmed_at=order.confirmed_at,
                shipped_at=order.shipped_at,
                delivered_at=order.delivered_at,
                cancelled_at=order.cancelled_at,
                cancellation_reason=order.cancellation_reason,
                customer_ref=order.customer_ref,
            )
            self._session.add(row)
        else:
            existing.status = order.status.value
            existing.shipped_at = order.shipped_at
            existing.delivered_at = order.delivered_at
            existing.cancelled_at = order.cancelled_at
            existing.cancellation_reason = order.cancellation_reason

    def find_by_id(self, order_id: OrderId) -> Order | None:
        row = self._session.get(OrderRow, str(order_id))
        return self._row_to_order(row) if row else None

    def find_by_reservation_id(self, reservation_id: ReservationId) -> Order | None:
        row = self._session.execute(
            select(OrderRow).where(OrderRow.reservation_id == str(reservation_id))
        ).scalar_one_or_none()
        return self._row_to_order(row) if row else None

    def _row_to_order(self, row: OrderRow) -> Order:
        return Order(
            id=OrderId(row.id),
            reservation_id=ReservationId(row.reservation_id),
            payment_intent_id=PaymentIntentId(row.payment_intent_id),
            item_id=ItemId(row.item_id),
            amount=Decimal(str(row.amount)),
            currency=row.currency,
            status=OrderStatus(row.status),
            created_at=row.created_at,
            confirmed_at=row.confirmed_at,
            shipped_at=row.shipped_at,
            delivered_at=row.delivered_at,
            cancelled_at=row.cancelled_at,
            cancellation_reason=row.cancellation_reason,
            customer_ref=row.customer_ref,
        )


class SQLAlchemyOrderOutbox:
    """Shares the outbox_events table with Reservation and Payment outboxes."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def enqueue(self, event: DomainEvent) -> None:
        row = OutboxEventRow(
            event_id=event.event_id,
            event_type=event.event_type,
            payload=json.dumps(asdict(event), default=_json_default),
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(row)
