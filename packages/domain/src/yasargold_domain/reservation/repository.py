"""Repository Protocols for the Reservation bounded context.

Protocols define what ReservationService needs from infrastructure.
Concrete implementations (PostgreSQL, Redis) live in the application layer.

All IDs are typed (ItemId, ReservationId, etc.) so the compiler catches
mix-ups like passing a QuoteId where an ItemId is expected.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from yasargold_domain.reservation.events import DomainEvent
from yasargold_domain.shared.identifiers import (
    GoldPriceId,
    ItemId,
    QuoteId,
    ReservationId,
)


@dataclass(frozen=True)
class ReservationRecord:
    """Persisted state of a confirmed reservation (write model).

    Read models are separate projections in the API layer.
    All monetary fields are Decimal — no float in financial records.
    """
    id: ReservationId
    quote_id: QuoteId
    item_id: ItemId
    gold_price_id: GoldPriceId
    locked_rate_per_gram_24k: Decimal
    karat_rate_per_gram: Decimal
    pricing_engine_version: str
    reserved_at: datetime
    valid_until: datetime
    status: str  # ACTIVE | EXPIRED | CANCELLED | COMPLETED
    customer_phone: str | None = None  # captured at reservation for Sprint 6 notifications


class InventoryReservationRepository(Protocol):
    """What ReservationService needs from the inventory store.

    All methods run inside a single DB transaction owned by the service.
    The implementation decides the locking strategy:
        Today:   SELECT FOR UPDATE NOWAIT + Partial Unique Index (INV-6)
        Future:  Redis SETNX or distributed lock — no domain change required.

    Atomicity contract:
        lock_item() for the same item_id must be serialisable:
        concurrent calls succeed for exactly one caller, others raise.
    """

    def lock_item(self, item_id: ItemId, quote_id: QuoteId, valid_until: datetime) -> bool:
        """Attempt to lock *item_id* until *valid_until*.

        Returns True if the lock was acquired.
        Raises ItemAlreadyReservedException if another reservation holds the lock.
        Must be idempotent for the same (item_id, quote_id) pair.
        """
        ...

    def save_reservation(self, record: ReservationRecord) -> None:
        """Persist a confirmed reservation record."""
        ...

    def release_lock(self, item_id: ItemId, quote_id: QuoteId) -> None:
        """Release the lock on *item_id* (expiry or cancellation)."""
        ...

    def find_by_quote_id(self, quote_id: QuoteId) -> ReservationRecord | None:
        """Return the reservation for *quote_id*, or None if not found."""
        ...

    def find_by_id(self, reservation_id: ReservationId) -> ReservationRecord | None:
        """Return the reservation for *reservation_id*, or None if not found."""
        ...

    def update_status(self, reservation_id: ReservationId, status: str) -> None:
        """Update the status of the given reservation in place."""
        ...

    def find_elapsed_active(self, now: datetime, limit: int = 100) -> list[ReservationRecord]:
        """Return ACTIVE reservations whose valid_until has elapsed.

        Used by the Expiry Worker to transition stale reservations.
        *limit* prevents unbounded queries on large tables.
        """
        ...


class ReservationEventOutbox(Protocol):
    """Transactional Outbox — receives typed Domain Events, not raw dicts.

    ADR-007: events enqueued here must be DomainEvent instances defined in
    packages/domain. Application code must never pass raw dicts or payloads.

    The Outbox implementation serialises the event to JSON/bytes for transport.
    Domain code never knows about serialisation format or message broker.

    Delivery guarantee: at-least-once.
    Deduplication: consumers use event.event_id (UUID) for idempotency.
    """

    def enqueue(self, event: DomainEvent) -> None:
        """Write *event* to the outbox within the current transaction.

        Called inside the same DB transaction as save_reservation().
        The background Worker reads and publishes after commit.
        """
        ...
