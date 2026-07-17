"""Reservation domain events — first-class citizens of the domain model.

These are facts that happened in the business domain. They are:
  - Immutable (frozen dataclass)
  - Self-describing (carry all data needed to reconstruct the fact)
  - Infrastructure-agnostic (no Kafka, no Redis, no JSON serialization)

The Outbox infrastructure receives DomainEvent instances and serialises them.
Application code never constructs raw dicts for the Outbox.

ADR-007: Domain Events Are First-Class Citizens.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from yasargold_domain.shared.identifiers import GoldPriceId, ItemId, PaymentIntentId, QuoteId, ReservationId


def _new_event_id() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class DomainEvent:
    """Base class for all domain events.

    event_id:    UUID for idempotency — consumers deduplicate on this.
    occurred_at: When the fact happened in the domain (not when it was published).
    event_type:  Fully-qualified event name for routing and deserialization.
    """
    event_id: str = field(default_factory=_new_event_id)
    occurred_at: datetime = field(default_factory=_utcnow)

    @property
    def event_type(self) -> str:
        return f"{self.__class__.__module__}.{self.__class__.__qualname__}"


@dataclass(frozen=True)
class ReservationCreated(DomainEvent):
    """A Quote was successfully converted to an active Reservation.

    Published after:
        - CompositePolicy passes
        - Inventory is locked
        - ReservationRecord is persisted
        - Outbox entry is written (same transaction)

    Consumers: payment gateway notification, confirmation SMS, analytics.
    """
    reservation_id: ReservationId = field(default=ReservationId(""))
    quote_id: QuoteId = field(default=QuoteId(""))
    item_id: ItemId = field(default=ItemId(0))
    gold_price_id: GoldPriceId = field(default=GoldPriceId(0))
    locked_rate_per_gram_24k: Decimal = field(default=Decimal("0"))
    pricing_engine_version: str = field(default="")
    valid_until: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True)
class ReservationExpired(DomainEvent):
    """A Reservation's valid_until elapsed without progressing to Checkout.

    Published by the expiry Worker after detecting elapsed reservations.
    Consumers: inventory release, customer notification, analytics.
    """
    reservation_id: ReservationId = field(default=ReservationId(""))
    quote_id: QuoteId = field(default=QuoteId(""))
    item_id: ItemId = field(default=ItemId(0))
    expired_at: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True)
class ReservationCancelled(DomainEvent):
    """A Reservation was explicitly cancelled before expiry.

    cancelled_by: "customer" | "system" | "admin"
    Consumers: inventory release, customer notification.
    """
    reservation_id: ReservationId = field(default=ReservationId(""))
    quote_id: QuoteId = field(default=QuoteId(""))
    item_id: ItemId = field(default=ItemId(0))
    cancelled_by: str = field(default="")


@dataclass(frozen=True)
class ReservationConfirmed(DomainEvent):
    """Payment succeeded and the Reservation moved to Confirmed (pre-Order).

    payment_intent_id: internal PaymentIntentId (not the gateway reference).
    Consumers: order creation, inventory deduction, accounting journal.
    """
    reservation_id: ReservationId = field(default=ReservationId(""))
    quote_id: QuoteId = field(default=QuoteId(""))
    item_id: ItemId = field(default=ItemId(0))
    payment_intent_id: PaymentIntentId = field(default=PaymentIntentId(""))
    confirmed_at: datetime = field(default_factory=_utcnow)
