"""LogNotificationGateway — structured-log adapter for dev and test environments.

Implements NotificationGateway Protocol. Never calls a real provider.
Use this in local dev and contract tests; swap for a real adapter in staging/prod.
"""
from __future__ import annotations

import logging

from yasargold_domain.notifications.channels import NotificationChannel, NotificationTemplate

log = logging.getLogger(__name__)


class LogNotificationGateway:
    """Writes notification attempts to the structured log. No real send."""

    def send(
        self,
        channel: NotificationChannel,
        recipient: str,
        template: NotificationTemplate,
        variables: dict[str, str],
        idempotency_key: str | None = None,
    ) -> str:
        log.info(
            "notification.send",
            extra={
                "channel": channel.value,
                "recipient": recipient,
                "template": template.value,
                "variables": variables,
                "idempotency_key": idempotency_key,
            },
        )
        return f"log_{channel.value.lower()}_{template.value.lower()}"
