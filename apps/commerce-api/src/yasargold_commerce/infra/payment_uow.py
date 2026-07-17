"""SQLAlchemy implementation of PaymentUnitOfWork."""
from __future__ import annotations

from sqlalchemy.orm import Session

from yasargold_commerce.infra.payment_store import (
    SQLAlchemyPaymentIntentRepository,
    SQLAlchemyPaymentOutbox,
)


class SQLAlchemyPaymentUnitOfWork:
    def __init__(self, session: Session) -> None:
        self._session = session
        self.repository = SQLAlchemyPaymentIntentRepository(session)
        self.outbox = SQLAlchemyPaymentOutbox(session)

    def __enter__(self) -> SQLAlchemyPaymentUnitOfWork:
        return self

    def __exit__(self, exc_type: object, *args: object) -> None:
        if exc_type is not None:
            self.rollback()

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
