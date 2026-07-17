"""SQLAlchemy implementation of NotificationRepository."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from yasargold_domain.notifications.channels import NotificationChannel, NotificationTemplate
from yasargold_domain.notifications.notification import Notification, NotificationStatus
from yasargold_domain.shared.identifiers import OrderId

from yasargold_commerce.infra.notification_orm import NotificationRow


class SQLAlchemyNotificationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, notification: Notification) -> None:
        existing = self._session.get(NotificationRow, notification.id)
        if existing is None:
            self._session.add(NotificationRow(
                id=notification.id,
                order_id=str(notification.order_id),
                channel=notification.channel.value,
                recipient=notification.recipient,
                template=notification.template.value,
                status=notification.status.value,
                created_at=notification.created_at,
                sent_at=notification.sent_at,
                failure_reason=notification.failure_reason,
            ))
        else:
            existing.status = notification.status.value
            existing.sent_at = notification.sent_at
            existing.failure_reason = notification.failure_reason

    def find_by_order_id(self, order_id: OrderId) -> list[Notification]:
        rows = self._session.execute(
            select(NotificationRow).where(NotificationRow.order_id == str(order_id))
        ).scalars().all()
        return [self._row_to_domain(r) for r in rows]

    def _row_to_domain(self, row: NotificationRow) -> Notification:
        return Notification(
            id=row.id,
            order_id=OrderId(row.order_id),
            channel=NotificationChannel(row.channel),
            recipient=row.recipient,
            template=NotificationTemplate(row.template),
            status=NotificationStatus(row.status),
            created_at=row.created_at,
            sent_at=row.sent_at,
            failure_reason=row.failure_reason,
        )
