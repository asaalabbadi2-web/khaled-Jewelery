"""Repository and UnitOfWork Protocols for the Notifications context."""
from __future__ import annotations

from typing import Protocol

from yasargold_domain.notifications.notification import Notification
from yasargold_domain.shared.identifiers import OrderId


class NotificationRepository(Protocol):
    def save(self, notification: Notification) -> None:
        """INSERT or UPDATE a notification record."""
        ...

    def find_by_order_id(self, order_id: OrderId) -> list[Notification]:
        """Return all notifications for an order (for idempotency checks)."""
        ...


class NotificationUnitOfWork(Protocol):
    repository: NotificationRepository

    def __enter__(self) -> NotificationUnitOfWork: ...
    def __exit__(self, *args: object) -> None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
