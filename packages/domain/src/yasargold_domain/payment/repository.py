"""Repository Protocols for the Payment bounded context.

Two distinct protocols with distinct responsibilities:
    PaymentIntentRepository  — persists and retrieves PaymentIntent aggregates
    PaymentEventOutbox       — writes domain events to the transactional outbox

Intentionally separated from PaymentGateway (see gateway.py):
    Repository: talks to the database (our system of record)
    Gateway:    talks to the external payment provider (Moyasar, Tap, etc.)

Swapping a payment provider requires only a new Gateway adapter — the
Repository protocol and its SQL implementation stay unchanged.
"""
from __future__ import annotations

from typing import Protocol

from yasargold_domain.payment.intent import PaymentIntent
from yasargold_domain.reservation.events import DomainEvent
from yasargold_domain.shared.identifiers import PaymentIntentId


class PaymentIntentRepository(Protocol):
    """What PaymentService needs from the persistence store.

    All methods run inside a single DB transaction owned by the service.
    """

    def save(self, intent: PaymentIntent) -> None:
        """Persist or update a PaymentIntent.

        Insert on first call, UPDATE on subsequent calls for the same id.
        Must be idempotent for the same intent.id.
        """
        ...

    def get(self, intent_id: PaymentIntentId) -> PaymentIntent | None:
        """Return the PaymentIntent for *intent_id*, or None if not found."""
        ...

    def find_by_provider_reference(self, provider_reference: str) -> PaymentIntent | None:
        """Return the PaymentIntent with the given gateway reference, or None.

        Used by the webhook handler to look up the intent from the gateway's
        payment ID (e.g. Moyasar `id` field in the webhook payload).
        """
        ...


class PaymentEventOutbox(Protocol):
    """Transactional Outbox for payment domain events.

    Structurally identical to ReservationEventOutbox — both receive DomainEvent
    instances. Defined separately so the payment bounded context does not import
    from the reservation bounded context.

    Delivery guarantee: at-least-once.
    Deduplication: consumers use event.event_id (UUID) for idempotency.
    """

    def enqueue(self, event: DomainEvent) -> None:
        """Write *event* to the outbox within the current transaction.

        The background Worker reads and publishes after commit.
        """
        ...
