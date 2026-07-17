"""PaymentGateway Protocol — the boundary between domain and payment providers.

This Protocol defines what PaymentService needs from a payment gateway.
Concrete implementations (MoyasarAdapter, TapAdapter, …) live in the
infrastructure layer and are never imported by domain code.

Design:
    - CheckoutUrl is a domain value object: a URL + provider reference.
      The domain only passes it to the caller — it never inspects the URL format.
    - WebhookResult is a parsed, provider-agnostic fact:
      "this payment succeeded / failed with these details."
      The adapter translates provider-specific JSON into this struct.
    - PaymentGateway.parse_webhook() MUST verify the signature before
      returning. If the signature is invalid, it raises — never returns
      a partial result.

Adding a new payment provider = new class implementing PaymentGateway.
Zero changes to PaymentService or PaymentIntent.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from yasargold_domain.payment.intent import PaymentIntent
from yasargold_domain.shared.identifiers import PaymentFailureReason


@dataclass(frozen=True)
class CheckoutUrl:
    """The gateway's response to initiating a payment session.

    url:                Redirect the customer here to complete payment.
    provider_reference: The gateway's own payment identifier.
                        Stored on PaymentIntent so the webhook can look it up.
    """
    url: str
    provider_reference: str


@dataclass(frozen=True)
class WebhookResult:
    """Parsed, signature-verified result from a payment provider webhook.

    outcome:          "paid" | "failed" — the only two facts the domain cares about.
    provider_reference: matches the CheckoutUrl.provider_reference stored earlier.
    paid_at:          When the charge was captured (None if outcome == "failed").
    failure_reason:   Opaque label from the adapter (None if outcome == "paid").
                      The domain never inspects this string's format.
    """
    provider_reference: str
    outcome: Literal["paid", "failed"]
    paid_at: datetime | None
    failure_reason: PaymentFailureReason | None


class PaymentGateway(Protocol):
    """What PaymentService needs from a payment provider.

    One implementation per provider (MoyasarGateway, TapGateway, …).
    The service is constructed with a gateway instance and never knows which
    concrete adapter it holds.
    """

    def initiate(self, intent: PaymentIntent, callback_url: str) -> CheckoutUrl:
        """Open a payment session with the provider.

        Args:
            intent:       The PaymentIntent to pay (amount, currency, id).
            callback_url: Where the provider should send the webhook.

        Returns:
            CheckoutUrl with the redirect URL and provider_reference.

        Raises:
            Any exception — PaymentService treats all gateway errors as fatal
            and rolls back without saving the intent.
        """
        ...

    def parse_webhook(self, payload: bytes, signature: str) -> WebhookResult:
        """Verify signature and parse an incoming webhook payload.

        Args:
            payload:   Raw request body (bytes) from the provider.
            signature: Value of the provider's signature header.

        Returns:
            WebhookResult with outcome, provider_reference, and timing.

        Raises:
            Any exception on invalid signature or unrecognised payload format.
            HTTP handler must return 400 to prevent webhook retries.
        """
        ...
