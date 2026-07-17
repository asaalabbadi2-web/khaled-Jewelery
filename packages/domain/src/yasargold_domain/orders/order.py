"""Order aggregate — the central business record of a completed sale.

An Order is created atomically when payment is confirmed (CheckoutService.confirm()).
It owns the full lifecycle from CONFIRMED → DELIVERED (or CANCELLED).

State machine:
    CONFIRMED → READY_FOR_SHIPMENT → SHIPPED → DELIVERED
                                              ↘
                                            CANCELLED  (from any non-terminal state)

PENDING is reserved for future use (COD, BNPL). In the current flow all orders
start as CONFIRMED since payment has already been received before creation.

Inventory contract:
    Item transitions: AVAILABLE → RESERVED (at Reservation) → SOLD (at Order creation).
    The OrderCreated event carries item_id so the ERP consumer can update item status.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from yasargold_domain.shared.identifiers import ItemId, OrderId, PaymentIntentId, ReservationId


class OrderStatus(str, Enum):
    PENDING             = "PENDING"
    CONFIRMED           = "CONFIRMED"
    READY_FOR_SHIPMENT  = "READY_FOR_SHIPMENT"
    SHIPPED             = "SHIPPED"
    DELIVERED           = "DELIVERED"
    CANCELLED           = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in (OrderStatus.DELIVERED, OrderStatus.CANCELLED)


@dataclass(frozen=True)
class Order:
    """Immutable snapshot of an Order at a point in time.

    All mutations return a new Order instance (value-object style).
    Persistence uses OrderRepository.save() which INSERT-or-UPDATEs.
    """
    id: OrderId
    reservation_id: ReservationId
    payment_intent_id: PaymentIntentId
    item_id: ItemId
    amount: Decimal
    currency: str
    status: OrderStatus
    created_at: datetime
    confirmed_at: datetime | None = None
    shipped_at: datetime | None = None
    delivered_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None
    # Populated from Reservation.customer_phone at creation. Used for BOLA ownership
    # checks: find_order_for_customer() returns None if this != caller's JWT sub.
    # Null on orders created before v1.4 auth was wired — those are dev/test records.
    customer_ref: str | None = None

    # ------------------------------------------------------------------
    # Guard predicates — answer "can this transition happen?"
    # ------------------------------------------------------------------

    def can_ship(self) -> bool:
        return self.status == OrderStatus.CONFIRMED

    def can_mark_ready(self) -> bool:
        return self.status == OrderStatus.CONFIRMED

    def can_deliver(self) -> bool:
        return self.status == OrderStatus.SHIPPED

    def can_cancel(self) -> bool:
        return not self.status.is_terminal

    @property
    def is_terminal(self) -> bool:
        return self.status.is_terminal
