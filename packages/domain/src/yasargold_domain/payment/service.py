"""PaymentService — orchestrates the PaymentIntent lifecycle.

Holds NO business logic of its own. Every decision delegates to:
  - PaymentIntent.can_pay(now)     → domain aggregate (state machine)
  - PaymentGateway.initiate(...)   → infrastructure (external call)
  - PaymentIntentRepository        → infrastructure (persistence)
  - PaymentEventOutbox             → infrastructure (outbox)

Two operations only:
    issue()    → create PaymentIntent + open gateway session
    confirm()  → process webhook result → PAID or FAILED

Commit is the caller's responsibility:
    with uow:
        intent, url = service.issue(reservation_id, amount, ..., uow)
        uow.commit()

IMPORTANT — transaction boundary for issue():
    gateway.initiate() is called BEFORE saving the intent. If the gateway
    call fails, nothing is persisted. If the DB save fails after a successful
    gateway call, the intent is orphaned at the provider — the caller must
    handle this (e.g. cancel the session via a compensating call). This is
    an accepted trade-off: an orphaned gateway session expires harmlessly,
    while a persisted intent with no gateway session is a worse inconsistency.

Sequence — issue():
    caller
      │
      ├─ create PaymentIntent(PENDING)         no I/O
      │
      ├─ gateway.initiate(intent, callback)    external HTTP call
      │
      ├─ intent ← replace(provider_reference=…)
      │
      ├─ uow.repository.save(intent)
      │
      ├─ uow.outbox.enqueue(PaymentIntentCreated)
      │
      └─ return (intent, checkout_url)         caller commits

Sequence — confirm():
    caller (webhook handler)
      │
      ├─ uow.repository.find_by_provider_reference(…)
      │
      ├─ intent.can_pay(now) / is_terminal checks
      │
      ├─ intent ← replace(status=PAID|FAILED, paid_at|failure_reason)
      │
      ├─ uow.repository.save(intent)
      │
      ├─ uow.outbox.enqueue(PaymentReceived|PaymentFailed)
      │
      └─ return updated intent                caller commits
"""
from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from yasargold_domain.payment.events import (
    PaymentFailed,
    PaymentIntentCreated,
    PaymentReceived,
    RefundConfirmed,
)
from yasargold_domain.payment.exceptions import (
    PaymentIntentExpiredError,
    PaymentIntentNotFoundException,
    PaymentIntentStatusError,
)
from yasargold_domain.payment.gateway import PaymentGateway, WebhookResult
from yasargold_domain.payment.intent import PaymentIntent, PaymentStatus
from yasargold_domain.payment.unit_of_work import PaymentUnitOfWork
from yasargold_domain.shared.identifiers import PaymentIntentId, ReservationId


class PaymentService:
    """Orchestrates PaymentIntent creation and webhook processing.

    Constructed once and reused across requests (stateless).
    Receives a gateway instance at construction; receives UoW per call.
    """

    def __init__(self, gateway: PaymentGateway) -> None:
        self._gateway = gateway

    def issue(
        self,
        reservation_id: ReservationId,
        amount: Decimal,
        currency: str,
        expires_at: datetime,
        callback_url: str,
        uow: PaymentUnitOfWork,
        now: datetime | None = None,
    ) -> tuple[PaymentIntent, str]:
        """Create a PaymentIntent and open a gateway session.

        Args:
            reservation_id: The reservation being paid for.
            amount:         Exact amount to charge (Decimal, no float).
            currency:       ISO 4217 code (e.g. "SAR").
            expires_at:     When this payment window closes (= reservation.valid_until).
            callback_url:   Where the provider sends the webhook after payment.
            uow:            Open Unit of Work. Caller commits after this returns.
            now:            Explicit clock for testability. Defaults to UTC now.

        Returns:
            (PaymentIntent with status=PENDING, checkout_url string).

        Raises:
            Any exception from gateway.initiate() — caller handles and rolls back.
        """
        t = now or datetime.now(timezone.utc)

        intent_id = PaymentIntentId(f"pi_{uuid.uuid4().hex[:16]}")
        intent = PaymentIntent(
            id=intent_id,
            reservation_id=reservation_id,
            amount=amount,
            currency=currency,
            status=PaymentStatus.PENDING,
            created_at=t,
            expires_at=expires_at,
        )

        # Gateway call is OUTSIDE the transaction — see module docstring.
        checkout = self._gateway.initiate(intent, callback_url)

        intent = replace(
            intent,
            provider_reference=checkout.provider_reference,
        )

        uow.repository.save(intent)
        uow.outbox.enqueue(
            PaymentIntentCreated(
                payment_intent_id=intent_id,
                reservation_id=reservation_id,
                amount=amount,
                currency=currency,
                provider_reference=checkout.provider_reference,
                expires_at=expires_at,
            )
        )

        return intent, checkout.url

    def confirm(
        self,
        webhook_result: WebhookResult,
        uow: PaymentUnitOfWork,
        now: datetime | None = None,
    ) -> PaymentIntent:
        """Transition a PaymentIntent based on a verified webhook result.

        Args:
            webhook_result: Parsed, signature-verified result from the gateway adapter.
            uow:            Open Unit of Work. Caller commits after this returns.
            now:            Explicit clock for testability. Defaults to UTC now.

        Returns:
            Updated PaymentIntent with status=PAID or FAILED.

        Raises:
            PaymentIntentNotFoundException: provider_reference not found.
            PaymentIntentStatusError:       intent is already in a terminal state.
            PaymentIntentExpiredError:      expires_at elapsed before payment arrived.
        """
        t = now or datetime.now(timezone.utc)

        intent = uow.repository.find_by_provider_reference(webhook_result.provider_reference)
        if intent is None:
            raise PaymentIntentNotFoundException(webhook_result.provider_reference)

        # confirm() is only valid on PENDING intents.
        # PAID/REFUND_PENDING are non-terminal but already processed — idempotency guard.
        if intent.status != PaymentStatus.PENDING:
            raise PaymentIntentStatusError(
                str(intent.id),
                current_status=intent.status.value,
                expected="PENDING",
            )

        if webhook_result.outcome == "paid":
            if not intent.can_pay(t):
                raise PaymentIntentExpiredError(str(intent.id), expired_at=intent.expires_at)

            updated = replace(
                intent,
                status=PaymentStatus.PAID,
                paid_at=webhook_result.paid_at or t,
            )
            uow.outbox.enqueue(
                PaymentReceived(
                    payment_intent_id=intent.id,
                    reservation_id=intent.reservation_id,
                    amount=intent.amount,
                    currency=intent.currency,
                    provider_reference=webhook_result.provider_reference,
                    paid_at=updated.paid_at,  # type: ignore[arg-type]
                )
            )
        else:
            updated = replace(
                intent,
                status=PaymentStatus.FAILED,
                failure_reason=webhook_result.failure_reason,
            )
            uow.outbox.enqueue(
                PaymentFailed(
                    payment_intent_id=intent.id,
                    reservation_id=intent.reservation_id,
                    failure_reason=webhook_result.failure_reason,
                )
            )

        uow.repository.save(updated)
        return updated

    def mark_refund_pending(
        self,
        intent: PaymentIntent,
        uow: PaymentUnitOfWork,
    ) -> PaymentIntent:
        """Transition PAID → REFUND_PENDING (ADR-013 compensation path).

        Called by the webhook handler when Phase 2 cannot proceed:
        either the reservation expired or the item was sold at POS
        between reservation creation and payment capture.

        Raises:
            PaymentIntentStatusError: intent is not in PAID status.
        """
        if not intent.can_mark_refund_pending():
            raise PaymentIntentStatusError(
                str(intent.id),
                current_status=intent.status.value,
                expected="PAID",
            )
        updated = replace(intent, status=PaymentStatus.REFUND_PENDING)
        uow.repository.save(updated)
        return updated

    def mark_refunded(
        self,
        intent: PaymentIntent,
        uow: PaymentUnitOfWork,
        now: datetime | None = None,
    ) -> PaymentIntent:
        """Transition REFUND_PENDING → REFUNDED after provider confirms refund.

        Called by RefundWorker after the gateway call succeeds.
        Emits RefundConfirmed to the outbox for downstream consumers
        (customer notification, accounting journal reversal).

        Raises:
            PaymentIntentStatusError: intent is not in REFUND_PENDING status.
        """
        if not intent.can_mark_refunded():
            raise PaymentIntentStatusError(
                str(intent.id),
                current_status=intent.status.value,
                expected="REFUND_PENDING",
            )
        t = now or datetime.now(timezone.utc)
        updated = replace(intent, status=PaymentStatus.REFUNDED, refunded_at=t)
        uow.repository.save(updated)
        uow.outbox.enqueue(
            RefundConfirmed(
                payment_intent_id=intent.id,
                reservation_id=intent.reservation_id,
                amount=intent.amount,
                currency=intent.currency,
                refunded_at=t,
            )
        )
        return updated
