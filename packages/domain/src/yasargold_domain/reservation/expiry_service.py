"""ReservationExpiryService — transitions elapsed reservations to EXPIRED.

Run by a background scheduler (cron / APScheduler / Celery beat).

This is domain logic, not infrastructure:
  - The *definition* of "elapsed" belongs here (valid_until < now)
  - The *event* to emit when a reservation expires belongs here
  - The *query* to find elapsed reservations is an infrastructure detail
    injected via the UoW Protocol

Flow:
    Worker tick
        │
        ▼
    uow.repository.find_elapsed_active(now, limit)
        │
        ▼
    for each record:
        update_status(id, "EXPIRED")
        outbox.enqueue(ReservationExpired(...))
        │
        ▼
    uow.commit()
        │
        ▼
    return count_expired

At-most-once per worker tick per reservation:
    The query returns ACTIVE rows only; after update_status to EXPIRED,
    the row no longer appears in subsequent ticks.

Idempotency:
    If the worker crashes between update_status and commit, the next tick
    re-processes the same rows (still ACTIVE). The ReservationExpired event
    gets a new event_id, so consumers must deduplicate on reservation_id,
    not event_id, for expiry logic.
"""
from __future__ import annotations

from datetime import datetime, timezone

from yasargold_domain.reservation.events import ReservationExpired
from yasargold_domain.reservation.repository import ReservationRecord
from yasargold_domain.reservation.unit_of_work import ReservationUnitOfWork


class ReservationExpiryService:
    """Transitions elapsed ACTIVE reservations to EXPIRED in batch.

    Stateless — one instance per worker process.
    """

    def expire_elapsed(
        self,
        uow: ReservationUnitOfWork,
        now: datetime | None = None,
        limit: int = 100,
    ) -> list[ReservationRecord]:
        """Find and expire all ACTIVE reservations past their valid_until.

        Args:
            uow:   Open Unit of Work. Caller commits after this returns.
            now:   Explicit clock for testability. Defaults to UTC now.
            limit: Maximum reservations to process per tick (prevents
                   unbounded transactions on a large backlog).

        Returns:
            The ReservationRecords that were transitioned to EXPIRED.
            Callers use len(result) for the count and record.reserved_at
            for lifetime metrics — without re-querying the database.

        The caller is responsible for uow.commit(). This allows the Worker
        to add additional writes (e.g. notification preferences) before
        flushing.
        """
        t = now or datetime.now(timezone.utc)

        records = uow.repository.find_elapsed_active(t, limit=limit)
        for record in records:
            uow.repository.update_status(record.id, "EXPIRED")
            uow.outbox.enqueue(
                ReservationExpired(
                    reservation_id=record.id,
                    quote_id=record.quote_id,
                    item_id=record.item_id,
                    expired_at=t,
                )
            )

        return records
