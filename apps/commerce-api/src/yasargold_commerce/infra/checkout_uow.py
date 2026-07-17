"""SQLAlchemy implementation of CheckoutUnitOfWork.

Bridges reservation_repository + order_repository + outbox under ONE
Session so that Reservation(COMPLETED) and Order(CONFIRMED) commit or
roll back atomically in a single DB transaction.

This is the only UoW in Commerce that spans two domain repositories.
All three writes share self._session — there is one commit() call and
one rollback() call regardless of how many domain operations happen.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from yasargold_commerce.infra.order_store import SQLAlchemyOrderOutbox, SQLAlchemyOrderRepository
from yasargold_commerce.infra.reservation_store import SQLAlchemyInventoryRepository


class SQLAlchemyCheckoutUnitOfWork:
    def __init__(self, session: Session) -> None:
        self._session = session
        self.reservation_repository = SQLAlchemyInventoryRepository(session)
        self.repository = SQLAlchemyOrderRepository(session)
        self.outbox = SQLAlchemyOrderOutbox(session)

    def __enter__(self) -> SQLAlchemyCheckoutUnitOfWork:
        return self

    def __exit__(self, exc_type: object, *args: object) -> None:
        if exc_type is not None:
            self.rollback()

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
