"""SQLAlchemy implementation of NotificationUnitOfWork."""
from __future__ import annotations

from sqlalchemy.orm import Session

from yasargold_commerce.infra.notification_store import SQLAlchemyNotificationRepository


class SQLAlchemyNotificationUnitOfWork:
    def __init__(self, session: Session) -> None:
        self._session = session
        self.repository = SQLAlchemyNotificationRepository(session)

    def __enter__(self) -> SQLAlchemyNotificationUnitOfWork:
        return self

    def __exit__(self, exc_type: object, *args: object) -> None:
        if exc_type is not None:
            self.rollback()

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
