"""SQLAlchemy implementation of ShipmentUnitOfWork."""
from __future__ import annotations

from sqlalchemy.orm import Session

from yasargold_commerce.infra.shipment_store import (
    SQLAlchemyShipmentOutbox,
    SQLAlchemyShipmentRepository,
)


class SQLAlchemyShipmentUnitOfWork:
    def __init__(self, session: Session) -> None:
        self._session = session
        self.repository = SQLAlchemyShipmentRepository(session)
        self.outbox = SQLAlchemyShipmentOutbox(session)

    def __enter__(self) -> SQLAlchemyShipmentUnitOfWork:
        return self

    def __exit__(self, exc_type: object, *args: object) -> None:
        if exc_type is not None:
            self.rollback()

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
