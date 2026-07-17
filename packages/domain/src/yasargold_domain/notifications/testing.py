"""FakeNotificationGateway — in-memory stub for domain tests.

ADR-009: External Providers Are Adapters.
ADR-019: Every Protocol must have a Fake in {capability}/testing.py.

Usage:
    from yasargold_domain.notifications.testing import FakeNotificationGateway

    gw = FakeNotificationGateway()
    service = NotificationService(gw)
    ...
    assert gw.send_count == 1
    assert gw.last_recipient == "+966501234567"

Forced failures:
    gw = FakeNotificationGateway(fail_on_next=True)
    # next send() raises NotificationGatewayError
"""
from __future__ import annotations

from dataclasses import dataclass, field

from yasargold_domain.notifications.channels import NotificationChannel, NotificationTemplate
from yasargold_domain.notifications.exceptions import NotificationGatewayError


@dataclass
class FakeNotificationGateway:
    """In-memory NotificationGateway. Records all send calls. Never contacts a provider.

    Attributes:
        fail_on_next:  If True, the next send() raises NotificationGatewayError
                       and the flag self-clears.
        sent:          List of (channel, recipient, template, variables, idempotency_key)
                       tuples — one entry per successful send().
    """

    fail_on_next: bool = False
    sent: list[tuple] = field(default_factory=list)

    def send(
        self,
        channel: NotificationChannel,
        recipient: str,
        template: NotificationTemplate,
        variables: dict[str, str],
        idempotency_key: str | None = None,
    ) -> str:
        if self.fail_on_next:
            self.fail_on_next = False
            raise NotificationGatewayError(channel.value, "FakeNotificationGateway: simulated failure")
        self.sent.append((channel, recipient, template, variables, idempotency_key))
        return f"fake_{channel.value.lower()}_{template.value.lower()}"

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    @property
    def send_count(self) -> int:
        return len(self.sent)

    @property
    def last_recipient(self) -> str | None:
        return self.sent[-1][1] if self.sent else None

    @property
    def last_template(self) -> NotificationTemplate | None:
        return self.sent[-1][2] if self.sent else None

    @property
    def last_idempotency_key(self) -> str | None:
        return self.sent[-1][4] if self.sent else None
