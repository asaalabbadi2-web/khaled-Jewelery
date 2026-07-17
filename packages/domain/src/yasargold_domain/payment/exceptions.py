"""Typed domain exceptions for the Payment bounded context.

Raised by PaymentService; caught by the application layer (HTTP webhook handler,
CLI command) and translated into user-facing error responses.

HTTP mapping (recommendation):
    PaymentIntentNotFoundException  → 404 Not Found
    PaymentIntentStatusError        → 409 Conflict
    PaymentIntentExpiredError       → 410 Gone
"""
from __future__ import annotations

from datetime import datetime


class PaymentDomainError(Exception):
    """Base class for all payment domain errors."""


class PaymentIntentNotFoundException(PaymentDomainError):
    """No PaymentIntent exists for the given provider_reference."""

    def __init__(self, provider_reference: str) -> None:
        self.provider_reference = provider_reference
        super().__init__(f"PaymentIntent with provider_reference '{provider_reference}' not found")


class PaymentIntentStatusError(PaymentDomainError):
    """The intent is not in a state that permits the requested transition.

    Example: receiving a webhook for an already-PAID intent (double delivery).
    """

    def __init__(self, intent_id: str, current_status: str, expected: str) -> None:
        self.intent_id = intent_id
        self.current_status = current_status
        self.expected = expected
        super().__init__(
            f"PaymentIntent '{intent_id}' is {current_status}, expected {expected}"
        )


class PaymentIntentExpiredError(PaymentDomainError):
    """Payment webhook arrived after expires_at elapsed.

    HTTP handler should return 410 Gone — retrying the same payment_intent_id
    will never succeed; the customer must start a new Reservation.
    """

    def __init__(self, intent_id: str, expired_at: datetime) -> None:
        self.intent_id = intent_id
        self.expired_at = expired_at
        super().__init__(f"PaymentIntent '{intent_id}' expired at {expired_at}")
