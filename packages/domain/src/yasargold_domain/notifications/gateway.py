"""NotificationGateway Protocol — provider-agnostic dispatch interface.

Implementations live in apps/commerce-api/infra/:
    LogNotificationGateway  — dev / test: logs only, no real send
    SmsGateway              — Sprint 6+: Twilio / Taqnyat / unifonic

The domain never imports a provider SDK (ADR-009).
"""
from __future__ import annotations

from typing import Protocol

from yasargold_domain.notifications.channels import NotificationChannel, NotificationTemplate


class NotificationGateway(Protocol):
    """Send a single notification and return the provider reference.

    Args:
        channel:          SMS / EMAIL / WHATSAPP / PUSH
        recipient:        Phone in E.164 for SMS; email address for EMAIL
        template:         Logical template id — the gateway resolves to provider content
        variables:        Template variable substitution dict (e.g. {"order_id": "ord_abc"})
        idempotency_key:  Stable key passed to the provider to prevent duplicate sends
                          if the caller retries after a crash. Callers MUST set this to
                          ``f"{order_id}:{template.value}:{channel.value}"``.
                          Providers that support idempotency (Twilio, Unifonic) deduplicate
                          on their side; LogNotificationGateway logs it for observability.
                          This is the closure for the network-send atomicity gap: a local
                          transaction cannot prevent a duplicate send if the process crashes
                          after the provider ACKs but before uow.commit() — the provider's
                          deduplication is the only safe guard (ADR-014 §Atomicity).

    Returns:
        provider_reference: opaque string for audit (Twilio SID, etc.)

    Raises:
        NotificationGatewayError: any failure during dispatch.
            The caller (NotificationService) catches this and records FAILED.
    """

    def send(
        self,
        channel: NotificationChannel,
        recipient: str,
        template: NotificationTemplate,
        variables: dict[str, str],
        idempotency_key: str | None = None,
    ) -> str:
        ...
