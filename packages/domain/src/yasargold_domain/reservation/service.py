"""ReservationService — application-layer orchestrator for the reservation flow.

Holds NO business logic of its own. Every decision delegates to:
  - Quote.can_reserve(now)      → domain aggregate (time + status gate)
  - CompositePolicy.check(...)  → pluggable pre-conditions
  - InventoryReservationRepository → infrastructure lock + persistence
  - ReservationEventOutbox          → transactional outbox

Commit is the caller's responsibility:
    with uow:
        locked_quote = service.reserve(quote, item_id, uow, now)
        uow.commit()      ← caller decides when to flush

This keeps the service testable without a database and lets the HTTP handler
add additional writes (e.g. audit log entry) before committing.

Sequence diagram:
    caller
      │
      ├─ quote.can_reserve(now)           no I/O
      │
      ├─ policy.check(quote, item_id, t)  cheap → expensive, short-circuit
      │
      ├─ uow.repository.lock_item(...)    SELECT FOR UPDATE NOWAIT
      │
      ├─ uow.repository.save_reservation(record)
      │
      ├─ uow.outbox.enqueue(ReservationCreated(...))
      │                                   ↑ same transaction as lock + record
      └─ return Quote(status=LOCKED, id=quote_id)
"""
from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timezone

from yasargold_domain.pricing.quotes import Quote, QuoteStatus
from yasargold_domain.pricing.reservation_policy import ReservationPolicy
from yasargold_domain.reservation.events import ReservationCreated
from yasargold_domain.reservation.exceptions import ReservationDenied
from yasargold_domain.reservation.repository import ReservationRecord
from yasargold_domain.reservation.unit_of_work import ReservationUnitOfWork
from yasargold_domain.shared.identifiers import GoldPriceId, ItemId, QuoteId, ReservationId


class ReservationService:
    """Orchestrates the Quote → Reservation transition.

    Constructed once and reused across requests (stateless).
    Receives UoW per call so each request has its own transaction.
    """

    def __init__(self, policy: ReservationPolicy) -> None:
        self._policy = policy

    def reserve(
        self,
        quote: Quote,
        item_id: ItemId,
        uow: ReservationUnitOfWork,
        now: datetime | None = None,
        customer_phone: str | None = None,
    ) -> tuple[Quote, ReservationId]:
        """Convert a valid Quote into an active Reservation.

        Args:
            quote:   The Quote to lock. Must be FRESH or LOCKED status.
            item_id: The item to reserve. Must match the Quote's item context.
            uow:     Open Unit of Work. Caller commits after this returns.
            now:     Explicit clock for testability. Defaults to UTC now.

        Returns:
            A new Quote instance with status=LOCKED and id=QuoteId assigned.
            The original quote is unchanged (immutable aggregate).

        Raises:
            ReservationDenied:           Policy check failed.
            ItemAlreadyReservedException: Infrastructure lock already held.
        """
        t = now or datetime.now(timezone.utc)

        result = self._policy.check(quote, item_id, t)
        if not result.allowed:
            raise ReservationDenied(result.rejection_reason, result.policy)  # type: ignore[arg-type]

        reservation_id = ReservationId(f"res_{uuid.uuid4().hex[:16]}")
        quote_id = quote.id if quote.id is not None else QuoteId(f"qt_{uuid.uuid4().hex[:16]}")

        uow.repository.lock_item(item_id, quote_id, quote.valid_until)

        record = ReservationRecord(
            id=reservation_id,
            quote_id=quote_id,
            item_id=item_id,
            gold_price_id=GoldPriceId(quote.gold_price_id),
            locked_rate_per_gram_24k=quote.gold_rate_per_gram_24k,
            karat_rate_per_gram=quote.karat_rate_per_gram,
            pricing_engine_version=quote.pricing_engine_version,
            reserved_at=t,
            valid_until=quote.valid_until,
            status="ACTIVE",
            customer_phone=customer_phone,
        )
        uow.repository.save_reservation(record)

        uow.outbox.enqueue(
            ReservationCreated(
                reservation_id=reservation_id,
                quote_id=quote_id,
                item_id=item_id,
                gold_price_id=GoldPriceId(quote.gold_price_id),
                locked_rate_per_gram_24k=quote.gold_rate_per_gram_24k,
                pricing_engine_version=quote.pricing_engine_version,
                valid_until=quote.valid_until,
            )
        )

        return replace(quote, status=QuoteStatus.LOCKED, id=quote_id), reservation_id

    def find_reservation_for_customer(
        self,
        reservation_id: ReservationId,
        customer_ref: str | None,
        uow: ReservationUnitOfWork,
    ) -> ReservationRecord | None:
        """Fetch a reservation only if it belongs to the caller.

        Law 5 (BOLA): ownership check lives in the domain service, not the router.
        The router maps None → 404. It never returns 403 — confirming a resource
        exists to an unauthorized caller is an oracle attack.

        customer_ref: opaque caller identity (JWT sub in v1.4; customer_phone in
        the interim). None → always returns None (deny by default when unauthenticated).

        In v1.4, customer_ref is a verified JWT sub claim injected by middleware.
        In v1.3, customer_phone is used as a weak stand-in — it is NOT verified;
        this method establishes the ownership-check pattern before JWT exists.
        """
        if customer_ref is None:
            return None
        record = uow.repository.find_by_id(reservation_id)
        if record is None:
            return None
        if record.customer_phone != customer_ref:
            return None
        return record
