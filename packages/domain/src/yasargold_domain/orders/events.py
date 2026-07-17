"""Order domain events.

OrderCreated is the most important event in Commerce — every downstream
capability (Shipping, Notifications, ERP Sync, Analytics, CRM) consumes it.

Consumers of OrderCreated:
    - SMS/Email notification worker
    - Shipping capability (Sprint 7)
    - ERP Sync (updates item status to SOLD)
    - Analytics / CRM
    - Loyalty program

Consumers of OrderCancelled:
    - Inventory release (item back to AVAILABLE)
    - Refund trigger
    - Customer notification
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from yasargold_domain.reservation.events import DomainEvent, _new_event_id, _utcnow
from yasargold_domain.shared.identifiers import (
    ItemId,
    OrderId,
    PaymentIntentId,
    ReservationId,
)


@dataclass(frozen=True)
class OrderCreated(DomainEvent):
    """An Order was successfully created from a confirmed payment.

    Published after:
        - Order aggregate persisted
        - Reservation transitioned to COMPLETED
        - Outbox entries written (same atomic transaction)

    The item_id is included so that ERP consumers can mark the item as SOLD
    without a separate lookup.
    """
    order_id: OrderId = field(default=OrderId(""))
    reservation_id: ReservationId = field(default=ReservationId(""))
    payment_intent_id: PaymentIntentId = field(default=PaymentIntentId(""))
    item_id: ItemId = field(default=ItemId(0))
    amount: Decimal = field(default=Decimal("0"))
    currency: str = field(default="SAR")
    created_at: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True)
class OrderCancelled(DomainEvent):
    """An Order was cancelled before delivery.

    cancellation_reason: human-readable label (e.g. "customer_request", "fraud").
    Consumers: inventory release, refund trigger, customer notification.
    """
    order_id: OrderId = field(default=OrderId(""))
    reservation_id: ReservationId = field(default=ReservationId(""))
    item_id: ItemId = field(default=ItemId(0))
    cancellation_reason: str = field(default="")
    cancelled_at: datetime = field(default_factory=_utcnow)
