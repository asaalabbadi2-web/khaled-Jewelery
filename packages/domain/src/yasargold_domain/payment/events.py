"""Payment domain events — first-class citizens of the payment model.

These are facts that happened in the business domain. They are:
  - Immutable (frozen dataclass)
  - Self-describing (carry all data needed to reconstruct the fact)
  - Infrastructure-agnostic (no Kafka, no Redis, no JSON serialization)

Consumers of PaymentIntentCreated:
    - SMS / email with payment link
    - Expiry scheduler (schedule a timeout job)

Consumers of PaymentReceived:
    - CheckoutService.confirm() (transition Reservation → COMPLETED)
    - Accounting journal (revenue recognition)
    - Analytics

Consumers of PaymentFailed:
    - Customer notification
    - Retry logic (if applicable)
    - Analytics
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from yasargold_domain.reservation.events import DomainEvent, _new_event_id, _utcnow
from yasargold_domain.shared.identifiers import (
    PaymentFailureReason,
    PaymentIntentId,
    ReservationId,
)


@dataclass(frozen=True)
class PaymentIntentCreated(DomainEvent):
    """A PaymentIntent was created and a gateway session was opened.

    Published after:
        - PaymentIntent persisted to repository
        - Gateway returned provider_reference (checkout URL obtained)
        - Outbox entry written (same transaction)

    Consumers: send payment link, schedule expiry job, analytics.
    """
    payment_intent_id: PaymentIntentId = field(default=PaymentIntentId(""))
    reservation_id: ReservationId = field(default=ReservationId(""))
    amount: Decimal = field(default=Decimal("0"))
    currency: str = field(default="SAR")
    provider_reference: str = field(default="")
    expires_at: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True)
class PaymentReceived(DomainEvent):
    """Webhook confirmed a successful charge — intent is now PAID.

    Published after:
        - PaymentIntent transitioned to PAID
        - Repository updated
        - Outbox entry written (same transaction)

    Consumers: CheckoutService.confirm(), accounting journal, analytics.
    """
    payment_intent_id: PaymentIntentId = field(default=PaymentIntentId(""))
    reservation_id: ReservationId = field(default=ReservationId(""))
    amount: Decimal = field(default=Decimal("0"))
    currency: str = field(default="SAR")
    provider_reference: str = field(default="")
    paid_at: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True)
class PaymentFailed(DomainEvent):
    """Webhook reported a failure or card decline — intent is now FAILED.

    failure_reason: opaque label from the gateway adapter
                    (e.g. "insufficient_funds", "card_declined").
                    The domain never inspects the format; consumers may.

    Consumers: customer notification, retry eligibility check, analytics.
    """
    payment_intent_id: PaymentIntentId = field(default=PaymentIntentId(""))
    reservation_id: ReservationId = field(default=ReservationId(""))
    failure_reason: PaymentFailureReason | None = field(default=None)


@dataclass(frozen=True)
class RefundConfirmed(DomainEvent):
    """Provider confirmed the refund was processed — intent is now REFUNDED.

    Published after:
        - RefundWorker called the gateway and received confirmation
        - PaymentIntent transitioned to REFUNDED
        - Repository updated (same transaction)

    Consumers: customer notification, accounting journal (debit revenue), analytics.
    """
    payment_intent_id: PaymentIntentId = field(default=PaymentIntentId(""))
    reservation_id: ReservationId = field(default=ReservationId(""))
    amount: Decimal = field(default=Decimal("0"))
    currency: str = field(default="SAR")
    refunded_at: datetime = field(default_factory=_utcnow)
