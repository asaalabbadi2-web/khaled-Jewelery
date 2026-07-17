"""Notification aggregate.

State machine:
    PENDING ──[gateway.send() succeeds]──► SENT     (terminal)
    PENDING ──[gateway.send() raises]────► FAILED   (terminal — retry is a new Notification)

Design notes:
    - One Notification per channel per triggering event.
      A single OrderCreated may produce 1 SMS + 1 WhatsApp = 2 Notification records.
    - Retries create new Notification records; the failed one is kept for audit.
    - recipient is opaque to the domain (phone number for SMS, email for EMAIL).
      The gateway validates format.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from yasargold_domain.notifications.channels import NotificationChannel, NotificationTemplate
from yasargold_domain.shared.identifiers import OrderId


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NotificationStatus(str, Enum):
    PENDING = "PENDING"
    SENT    = "SENT"
    FAILED  = "FAILED"

    @property
    def is_terminal(self) -> bool:
        return self in (NotificationStatus.SENT, NotificationStatus.FAILED)


@dataclass(frozen=True)
class Notification:
    """Immutable record of one notification dispatch attempt."""
    id: str
    order_id: OrderId
    channel: NotificationChannel
    recipient: str
    template: NotificationTemplate
    status: NotificationStatus
    created_at: datetime = field(default_factory=_utcnow)
    sent_at: datetime | None = None
    failure_reason: str | None = None

    def can_send(self) -> bool:
        return self.status == NotificationStatus.PENDING

    @property
    def is_terminal(self) -> bool:
        return self.status.is_terminal
