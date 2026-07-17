"""Unit of Work Protocols for the Orders bounded context.

Two protocols:

OrderUnitOfWork
    Atomic boundary for standalone order operations (cancel, ship, deliver).
    Has order repository + outbox.

CheckoutUnitOfWork
    Atomic boundary for the checkout flow: creates Order + completes Reservation
    in one DB transaction. Extends OrderUnitOfWork with reservation_repository.

    CheckoutUnitOfWork structurally satisfies OrderUnitOfWork (has .repository
    and .outbox), so it can be passed to OrderService.create_from_reservation().
"""
from __future__ import annotations

from typing import Protocol

from yasargold_domain.orders.repository import OrderEventOutbox, OrderRepository
from yasargold_domain.reservation.repository import InventoryReservationRepository


class OrderUnitOfWork(Protocol):
    repository: OrderRepository
    outbox: OrderEventOutbox

    def __enter__(self) -> OrderUnitOfWork: ...
    def __exit__(self, *args: object) -> None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


class CheckoutUnitOfWork(Protocol):
    """Bridges reservation + order writes in one atomic transaction.

    .repository and .outbox satisfy OrderUnitOfWork, so this UoW can be
    passed directly to OrderService.create_from_reservation().
    """
    reservation_repository: InventoryReservationRepository
    repository: OrderRepository
    outbox: OrderEventOutbox

    def __enter__(self) -> CheckoutUnitOfWork: ...
    def __exit__(self, *args: object) -> None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
