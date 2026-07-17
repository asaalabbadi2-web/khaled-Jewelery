"""SQLAlchemy implementation of ReservationUnitOfWork.

Wraps a single Session so that repository writes (ReservationRow)
and outbox writes (OutboxEventRow) commit or roll back together.

Usage in HTTP handler:
    with _get_uow(db) as uow:
        locked_quote = reservation_service.reserve(quote, item_id, uow, now)
        uow.commit()
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from yasargold_commerce.infra.reservation_store import (
    SQLAlchemyInventoryRepository,
    SQLAlchemyReservationOutbox,
)


class SQLAlchemyReservationUnitOfWork:
    def __init__(self, session: Session) -> None:
        self._session = session
        self.repository = SQLAlchemyInventoryRepository(session)
        self.outbox = SQLAlchemyReservationOutbox(session)

    def __enter__(self) -> SQLAlchemyReservationUnitOfWork:
        return self

    def __exit__(self, exc_type: object, *args: object) -> None:
        if exc_type is not None:
            self.rollback()

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
