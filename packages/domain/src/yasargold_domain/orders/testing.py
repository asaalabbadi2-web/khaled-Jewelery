"""Test doubles for the Orders bounded context.

FakeOrderRepository       — in-memory OrderRepository
FakeOrderUnitOfWork       — in-memory OrderUnitOfWork (for OrderService tests)
FakeCheckoutUnitOfWork    — in-memory CheckoutUnitOfWork (for CheckoutService tests)
    Includes both FakeOrderRepository and FakeReservationRepository.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from yasargold_domain.orders.order import Order
from yasargold_domain.reservation.events import DomainEvent
from yasargold_domain.reservation.repository import ReservationRecord
from yasargold_domain.shared.identifiers import OrderId, ReservationId


# ---------------------------------------------------------------------------
# Order fakes
# ---------------------------------------------------------------------------

@dataclass
class FakeOrderRepository:
    _orders: dict[str, Order] = field(default_factory=dict)

    def save(self, order: Order) -> None:
        self._orders[str(order.id)] = order

    def find_by_id(self, order_id: OrderId) -> Order | None:
        return self._orders.get(str(order_id))

    def find_by_reservation_id(self, reservation_id: ReservationId) -> Order | None:
        return next(
            (o for o in self._orders.values() if o.reservation_id == reservation_id),
            None,
        )


@dataclass
class FakeOrderOutbox:
    events: list[DomainEvent] = field(default_factory=list)

    def enqueue(self, event: DomainEvent) -> None:
        self.events.append(event)


@dataclass
class FakeOrderUnitOfWork:
    repository: FakeOrderRepository = field(default_factory=FakeOrderRepository)
    outbox: FakeOrderOutbox = field(default_factory=FakeOrderOutbox)
    committed: bool = False

    def __enter__(self) -> FakeOrderUnitOfWork:
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Checkout fake (bridges reservation + order)
# ---------------------------------------------------------------------------

@dataclass
class _FakeReservationRepo:
    """Minimal reservation repo for CheckoutUnitOfWork tests."""
    records: dict[str, ReservationRecord] = field(default_factory=dict)
    updated: list[tuple[str, str]] = field(default_factory=list)

    def lock_item(self, *a: Any) -> bool:
        return True

    def save_reservation(self, record: ReservationRecord) -> None:
        self.records[str(record.id)] = record

    def release_lock(self, *a: Any) -> None:
        pass

    def find_by_quote_id(self, quote_id: Any) -> ReservationRecord | None:
        return next((r for r in self.records.values() if r.quote_id == quote_id), None)

    def find_by_id(self, reservation_id: Any) -> ReservationRecord | None:
        return self.records.get(str(reservation_id))

    def update_status(self, reservation_id: Any, status: str) -> None:
        self.updated.append((str(reservation_id), status))
        key = str(reservation_id)
        if key in self.records:
            self.records[key] = replace(self.records[key], status=status)

    def find_elapsed_active(self, now: Any, limit: int = 100) -> list[ReservationRecord]:
        return []


@dataclass
class FakeCheckoutUnitOfWork:
    """Satisfies CheckoutUnitOfWork Protocol for use in CheckoutService tests."""
    reservation_repository: _FakeReservationRepo = field(default_factory=_FakeReservationRepo)
    repository: FakeOrderRepository = field(default_factory=FakeOrderRepository)
    outbox: FakeOrderOutbox = field(default_factory=FakeOrderOutbox)
    committed: bool = False

    def __enter__(self) -> FakeCheckoutUnitOfWork:
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        pass
