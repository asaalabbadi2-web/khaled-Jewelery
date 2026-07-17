"""RefundGateway Protocol — the boundary between domain and refund providers.

Separate from PaymentGateway because refunding is a distinct operation:
    - It requires the provider_reference of the original payment.
    - It may have different rate limits / error modes than initiating.
    - Some providers use a completely different API for refunds.

Adding a new refund provider = new class implementing RefundGateway.
Zero changes to RefundWorker.
"""
from __future__ import annotations

from typing import Protocol

from yasargold_domain.payment.intent import PaymentIntent


class RefundGateway(Protocol):
    """What RefundWorker needs from a payment provider's refund API."""

    def refund(self, intent: PaymentIntent) -> None:
        """Issue a full refund for the given payment intent.

        Args:
            intent: The REFUND_PENDING intent to refund.
                    intent.provider_reference identifies the charge at the provider.
                    intent.amount and intent.currency determine the refund amount.

        Returns:
            None on success.

        Raises:
            RefundTransientError: transient failure — retry later.
            RefundPermanentError: permanent failure — manual intervention needed.
            Any other exception is treated as transient by RefundWorker.
        """
        ...


class RefundTransientError(Exception):
    """Gateway returned a retriable error (5xx, timeout, rate limit)."""


class RefundPermanentError(Exception):
    """Gateway rejected the refund permanently (already refunded, invalid reference)."""
