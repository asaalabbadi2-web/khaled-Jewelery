"""PaymentIntent Aggregate — the business concept of an intent to pay.

State machine:
    PENDING ──── [webhook: success] ──▶ PAID ──── [late: reservation expired] ──▶ REFUND_PENDING
    PENDING ──── [webhook: failure] ──▶ FAILED                                        │
    PENDING ──── [expires_at elapsed] ──▶ EXPIRED                              [refund confirmed]
    PAID / FAILED / EXPIRED / REFUNDED — terminal, no further transitions             ▼
                                                                                   REFUNDED

Design principles:
    - Provider-agnostic: provider_reference is an opaque string from the
      gateway (e.g. Moyasar payment_id). The domain never inspects its format.
    - PaymentProvider is a typed label for audit/display — the domain never
      branches on its value (no if provider == "moyasar": ...).
    - State machine queries live here, not in the Service.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from yasargold_domain.shared.identifiers import (
    PaymentFailureReason,
    PaymentIntentId,
    PaymentProvider,
    ReservationId,
)


class PaymentStatus(str, Enum):
    """Lifecycle states of a payment intent.

    | Status         | Meaning                                              | is_terminal |
    |----------------|------------------------------------------------------|-------------|
    | PENDING        | Gateway session open, awaiting customer pay          | ❌           |
    | PAID           | Webhook confirmed successful charge                  | ❌ *         |
    | FAILED         | Webhook reported failure or card decline             | ✅           |
    | EXPIRED        | expires_at elapsed before payment received           | ✅           |
    | REFUND_PENDING | Money captured but business context collapsed        | ❌           |
    | REFUNDED       | Provider confirmed refund — money returned           | ✅           |

    * PAID is not terminal when the reservation had already expired at webhook time.
      In that case the flow is: PAID → REFUND_PENDING → REFUNDED.
      This is "Payment Succeeded with Business Failure" — not FAILED, not EXPIRED.
    """
    PENDING        = "PENDING"
    PAID           = "PAID"
    FAILED         = "FAILED"
    EXPIRED        = "EXPIRED"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED       = "REFUNDED"

    @property
    def is_terminal(self) -> bool:
        """No further transitions are possible from this status."""
        return self in (
            PaymentStatus.FAILED,
            PaymentStatus.EXPIRED,
            PaymentStatus.REFUNDED,
        )

    @property
    def needs_refund(self) -> bool:
        """True when money was captured but must be returned to the customer."""
        return self == PaymentStatus.REFUND_PENDING


@dataclass(frozen=True)
class PaymentIntent:
    """Immutable Aggregate capturing a single payment commitment.

    Transition rules (always pass `now` explicitly for testability):
        PENDING        → PAID           via confirm() when webhook reports success
        PENDING        → FAILED         via confirm() when webhook reports failure
        PENDING        → EXPIRED        via expire()  when expires_at elapses
        PAID           → REFUND_PENDING via mark_refund_pending() when reservation expired
        REFUND_PENDING → REFUNDED       via mark_refunded() when provider confirms refund

    All monetary amounts are Decimal — no float in financial records.
    """
    id: PaymentIntentId
    reservation_id: ReservationId
    amount: Decimal
    currency: str
    status: PaymentStatus
    created_at: datetime
    expires_at: datetime
    provider: PaymentProvider | None = None
    provider_reference: str | None = None
    paid_at: datetime | None = None
    failure_reason: PaymentFailureReason | None = None
    refunded_at: datetime | None = None

    # ------------------------------------------------------------------
    # State machine queries — always pass now for deterministic tests
    # ------------------------------------------------------------------

    def can_pay(self, now: datetime | None = None) -> bool:
        """True if a payment webhook can still be accepted (PENDING + not expired)."""
        if self.status != PaymentStatus.PENDING:
            return False
        t = now or datetime.now(timezone.utc)
        exp = self.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return t < exp

    def can_expire(self, now: datetime | None = None) -> bool:
        """True if the intent should be moved to EXPIRED (PENDING + past expires_at)."""
        if self.status != PaymentStatus.PENDING:
            return False
        t = now or datetime.now(timezone.utc)
        exp = self.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return t >= exp

    def can_confirm(self) -> bool:
        """True if the intent can drive CheckoutService (status == PAID)."""
        return self.status == PaymentStatus.PAID

    def can_mark_refund_pending(self) -> bool:
        """True when money was captured but the reservation had expired.

        This is the 'late webhook' scenario: payment succeeded after the
        reservation window closed. The business obligation is to refund.
        PAID is the only valid source state — REFUND_PENDING is not re-entrant.
        """
        return self.status == PaymentStatus.PAID

    def can_mark_refunded(self) -> bool:
        """True when the provider has confirmed the refund was processed."""
        return self.status == PaymentStatus.REFUND_PENDING

    @property
    def is_terminal(self) -> bool:
        """True if no further transitions are possible."""
        return self.status.is_terminal
