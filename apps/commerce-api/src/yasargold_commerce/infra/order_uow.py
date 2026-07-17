"""SQLAlchemy implementation of OrderUnitOfWork for standalone order transitions.

Used by the Shipping router for ship() and deliver() — operations that update
the Order without touching Reservation. For the full checkout flow (which must
atomically update both Reservation and Order), use SQLAlchemyCheckoutUnitOfWork.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from yasargold_commerce.infra.order_store import SQLAlchemyOrderOutbox, SQLAlchemyOrderRepository


class SQLAlchemyOrderUnitOfWork:
    def __init__(self, session: Session) -> None:
        self._session = session
        self.repository = SQLAlchemyOrderRepository(session)
        self.outbox = SQLAlchemyOrderOutbox(session)

    def __enter__(self) -> SQLAlchemyOrderUnitOfWork:
        return self

    def __exit__(self, exc_type: object, *args: object) -> None:
        if exc_type is not None:
            self.rollback()

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
