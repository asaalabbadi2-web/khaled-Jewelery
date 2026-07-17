"""Unit of Work Protocol for the Reservation bounded context.

Defines the transaction boundary that groups:
  - InventoryReservationRepository (item lock + reservation record)
  - ReservationEventOutbox (outbox entry)

All three writes must commit or rollback together. If the outbox entry
is missing, the Worker never publishes the event; if the lock is missing,
double-reservation is possible. Atomicity is non-negotiable here.

Usage (application layer):
    with uow:
        locked_quote = reservation_service.reserve(quote, item_id, uow, now)
        uow.commit()

The concrete implementation (SQLAlchemy, async, in-memory test stub) lives
in the application layer. Domain code only sees this Protocol.
"""
from __future__ import annotations

from typing import Protocol

from yasargold_domain.reservation.repository import (
    InventoryReservationRepository,
    ReservationEventOutbox,
)


class ReservationUnitOfWork(Protocol):
    """Atomic transaction boundary for the reservation flow.

    Invariant: repository and outbox share the same underlying session.
    A commit on one is a commit on both.

    Implementors must:
    - Begin the transaction on __enter__
    - Roll back (not commit) on __exit__ with an exception
    - Expose repository and outbox as attributes pointing to the same session
    """

    repository: InventoryReservationRepository
    outbox: ReservationEventOutbox

    def __enter__(self) -> ReservationUnitOfWork:
        ...

    def __exit__(self, *args: object) -> None:
        ...

    def commit(self) -> None:
        """Flush and commit all writes in this transaction."""
        ...

    def rollback(self) -> None:
        """Discard all writes since __enter__."""
        ...
