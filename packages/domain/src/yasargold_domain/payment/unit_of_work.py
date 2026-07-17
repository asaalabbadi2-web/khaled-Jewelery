"""Unit of Work Protocol for the Payment bounded context.

Groups PaymentIntentRepository and PaymentEventOutbox under a single
transaction boundary. Commit or rollback applies to both.

Usage (application layer):
    with uow:
        intent, url = payment_service.issue(reservation_id, amount, ..., uow)
        uow.commit()

The concrete implementation (SQLAlchemy session, in-memory test stub) lives
in the application layer. Domain code only sees this Protocol.
"""
from __future__ import annotations

from typing import Protocol

from yasargold_domain.payment.repository import PaymentEventOutbox, PaymentIntentRepository


class PaymentUnitOfWork(Protocol):
    """Atomic transaction boundary for the payment flow.

    Invariant: repository and outbox share the same underlying session.
    """

    repository: PaymentIntentRepository
    outbox: PaymentEventOutbox

    def __enter__(self) -> PaymentUnitOfWork:
        ...

    def __exit__(self, *args: object) -> None:
        ...

    def commit(self) -> None:
        """Flush and commit all writes in this transaction."""
        ...

    def rollback(self) -> None:
        """Discard all writes since __enter__."""
        ...
