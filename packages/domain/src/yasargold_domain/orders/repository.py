"""Repository Protocol for the Orders bounded context.

OrderRepository: persists and retrieves Order aggregates.
OrderEventOutbox: writes domain events to the transactional outbox.

Both run inside a single DB transaction owned by the service layer.
Structurally identical to PaymentEventOutbox — defined separately to avoid
cross-context imports (same pattern as payment/repository.py).
"""
from __future__ import annotations

from typing import Protocol

from yasargold_domain.orders.order import Order
from yasargold_domain.reservation.events import DomainEvent
from yasargold_domain.shared.identifiers import OrderId, ReservationId


class OrderRepository(Protocol):
    def save(self, order: Order) -> None:
        """Persist or update an Order. INSERT on first call, UPDATE on subsequent."""
        ...

    def find_by_id(self, order_id: OrderId) -> Order | None:
        """Return the Order for *order_id*, or None if not found."""
        ...

    def find_by_reservation_id(self, reservation_id: ReservationId) -> Order | None:
        """Return the Order linked to *reservation_id*, or None."""
        ...


class OrderEventOutbox(Protocol):
    """Transactional outbox for order domain events.

    Shares the same outbox_events table as Reservation and Payment outboxes.
    Defined separately so orders/ does not import from reservation/ or payment/.
    """

    def enqueue(self, event: DomainEvent) -> None:
        ...
