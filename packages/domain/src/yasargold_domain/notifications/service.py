"""NotificationService — dispatches notifications for domain events.

Responsibilities:
    - Build a Notification record (PENDING)
    - Call the gateway (provider-agnostic)
    - Record SENT or FAILED based on outcome
    - Persist via UoW

The service is stateless and gateway-injected.
No business logic for selecting channels or templates — that belongs to the
caller (NotificationWorker), which knows the triggering event.

ADR-009: domain never imports a provider SDK.
ADR-008: returns list[Notification] (facts), not int.
"""
from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timezone

from yasargold_domain.notifications.channels import NotificationChannel, NotificationTemplate
from yasargold_domain.notifications.exceptions import NotificationGatewayError
from yasargold_domain.notifications.gateway import NotificationGateway
from yasargold_domain.notifications.notification import Notification, NotificationStatus
from yasargold_domain.notifications.repository import NotificationUnitOfWork
from yasargold_domain.shared.identifiers import OrderId


class NotificationService:
    """Dispatches notifications via a provider-agnostic gateway.

    Constructed once and reused across requests (stateless).
    """

    def __init__(self, gateway: NotificationGateway) -> None:
        self._gateway = gateway

    def dispatch(
        self,
        order_id: OrderId,
        channel: NotificationChannel,
        recipient: str,
        template: NotificationTemplate,
        variables: dict[str, str],
        uow: NotificationUnitOfWork,
        now: datetime | None = None,
        idempotency_key: str | None = None,
    ) -> Notification:
        """Dispatch one notification and persist the outcome (single-commit path).

        Returns the Notification record in its final state (SENT or FAILED).
        Never raises — failures are recorded, not propagated.
        Caller commits after this returns.

        ATOMICITY WARNING: this method saves the result in a single commit after
        the gateway call. If the process crashes after gateway.send() succeeds but
        before uow.commit(), no SENT row is written — the gap is invisible.
        Before enabling a real SMS provider, switch to the claim-then-send pattern
        (ADR-014 §Atomicity): call claim(), commit, call gateway, call mark_result(),
        commit. The idempotency_key passed to gateway.send() is the closure for this
        gap at the provider level — it MUST be set for all production adapters.
        """
        t = now or datetime.now(timezone.utc)
        key = idempotency_key or f"{order_id}:{template.value}:{channel.value}"
        notification = Notification(
            id=f"ntf_{uuid.uuid4().hex[:16]}",
            order_id=order_id,
            channel=channel,
            recipient=recipient,
            template=template,
            status=NotificationStatus.PENDING,
            created_at=t,
        )

        try:
            self._gateway.send(channel, recipient, template, variables, key)
            result = replace(
                notification,
                status=NotificationStatus.SENT,
                sent_at=t,
                failure_reason=None,
            )
        except NotificationGatewayError as exc:
            result = replace(
                notification,
                status=NotificationStatus.FAILED,
                failure_reason=exc.reason,
            )

        uow.repository.save(result)
        return result

    def claim(
        self,
        order_id: OrderId,
        channel: NotificationChannel,
        recipient: str,
        template: NotificationTemplate,
        now: datetime,
        uow: NotificationUnitOfWork,
    ) -> Notification:
        """Phase 1 of claim-then-send: create and save a PENDING notification.

        Caller MUST commit after this returns, BEFORE calling the gateway.
        The committed PENDING row is the observable signal if the process crashes
        between network send and the subsequent mark_result() commit.
        """
        notification = Notification(
            id=f"ntf_{uuid.uuid4().hex[:16]}",
            order_id=order_id,
            channel=channel,
            recipient=recipient,
            template=template,
            status=NotificationStatus.PENDING,
            created_at=now,
        )
        uow.repository.save(notification)
        return notification

    def mark_result(
        self,
        notification: Notification,
        success: bool,
        provider_ref_or_error: str,
        now: datetime,
        uow: NotificationUnitOfWork,
    ) -> Notification:
        """Phase 2 of claim-then-send: update PENDING to SENT or FAILED.

        Call after gateway.send() returns or raises (caller catches).
        Caller must commit after this returns.
        """
        if success:
            result = replace(notification, status=NotificationStatus.SENT, sent_at=now)
        else:
            result = replace(notification, status=NotificationStatus.FAILED, failure_reason=provider_ref_or_error)
        uow.repository.save(result)
        return result

    def dispatch_all(
        self,
        order_id: OrderId,
        channels: list[tuple[NotificationChannel, str]],
        template: NotificationTemplate,
        variables: dict[str, str],
        uow: NotificationUnitOfWork,
        now: datetime | None = None,
    ) -> list[Notification]:
        """Dispatch to multiple channels, collecting all outcomes.

        Each channel is attempted independently — one failure does not
        block the others. Returns facts (ADR-008): list[Notification].
        """
        return [
            self.dispatch(order_id, channel, recipient, template, variables, uow, now)
            for channel, recipient in channels
        ]
