"""SQLAlchemy implementations of InventoryReservationRepository and ReservationEventOutbox.

Both operate on the same Session so they participate in the same transaction.
The UnitOfWork (reservation_uow.py) holds the session and exposes both.

Locking strategy (lock_item) — INV-6:
  Two-layer defence against double-reservation under concurrent load:

  Layer 1 — SELECT FOR UPDATE NOWAIT:
    Serialises concurrent reads on the same item_id. If another transaction
    is already reading/writing the same ACTIVE row, NOWAIT raises
    OperationalError immediately (no waiting). This catches the common case
    of two requests arriving within the same window.

  Layer 2 — Partial Unique Index:
    CREATE UNIQUE INDEX ix_reservations_active_item
        ON reservations (item_id) WHERE status = 'ACTIVE';
    Even if two transactions both SELECT and see nothing (race between SELECT
    and INSERT), only one INSERT can succeed. The other raises IntegrityError.

  Together they make double-reservation impossible without application-level
  distributed locking.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from yasargold_domain.reservation.events import DomainEvent
from yasargold_domain.reservation.exceptions import ItemAlreadyReservedException
from yasargold_domain.reservation.repository import ReservationRecord
from yasargold_domain.shared.identifiers import GoldPriceId, ItemId, QuoteId, ReservationId

from yasargold_commerce.infra.reservation_orm import OutboxEventRow, ReservationRow
from yasargold_commerce.metrics import RESERVATION_CONFLICT, RESERVATION_LOCK_DURATION


def _json_default(obj: object) -> str:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


class SQLAlchemyInventoryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def lock_item(self, item_id: ItemId, quote_id: QuoteId, valid_until: datetime) -> bool:
        """Attempt to acquire an exclusive lock on item_id.

        Uses SELECT FOR UPDATE NOWAIT (Layer 1) to serialise concurrent
        reads. The partial unique index (Layer 2) catches any INSERT races
        that slip past the SELECT gap.
        """
        now = datetime.now(timezone.utc)
        try:
            with RESERVATION_LOCK_DURATION.time():
                existing = self._session.execute(
                    select(ReservationRow)
                    .where(ReservationRow.item_id == int(item_id))
                    .where(ReservationRow.status == "ACTIVE")
                    .where(ReservationRow.valid_until > now)
                    .with_for_update(nowait=True)
                ).scalar_one_or_none()
        except OperationalError:
            RESERVATION_CONFLICT.inc()
            raise ItemAlreadyReservedException(int(item_id))
        if existing is not None:
            RESERVATION_CONFLICT.inc()
            raise ItemAlreadyReservedException(int(item_id))
        return True

    def save_reservation(self, record: ReservationRecord) -> None:
        """Persist the reservation row.

        If the partial unique index (item_id WHERE status='ACTIVE') fires,
        an IntegrityError is raised and translated to ItemAlreadyReservedException.
        This is Layer 2 of INV-6 — catches the INSERT race that slips past lock_item().
        """
        row = ReservationRow(
            id=str(record.id),
            quote_id=str(record.quote_id),
            item_id=int(record.item_id),
            gold_price_id=int(record.gold_price_id),
            locked_rate_per_gram_24k=str(record.locked_rate_per_gram_24k),
            karat_rate_per_gram=str(record.karat_rate_per_gram),
            pricing_engine_version=record.pricing_engine_version,
            reserved_at=record.reserved_at,
            valid_until=record.valid_until,
            status=record.status,
            customer_phone=record.customer_phone,
        )
        try:
            self._session.add(row)
            self._session.flush()  # surface IntegrityError before commit
        except IntegrityError:
            raise ItemAlreadyReservedException(int(record.item_id))

    def release_lock(self, item_id: ItemId, quote_id: QuoteId) -> None:
        self._session.execute(
            update(ReservationRow)
            .where(ReservationRow.item_id == int(item_id))
            .where(ReservationRow.quote_id == str(quote_id))
            .where(ReservationRow.status == "ACTIVE")
            .values(status="CANCELLED")
        )

    def find_by_quote_id(self, quote_id: QuoteId) -> ReservationRecord | None:
        row = self._session.execute(
            select(ReservationRow).where(ReservationRow.quote_id == str(quote_id))
        ).scalar_one_or_none()
        if row is None:
            return None
        return self._row_to_record(row)

    def find_by_id(self, reservation_id: ReservationId) -> ReservationRecord | None:
        row = self._session.execute(
            select(ReservationRow).where(ReservationRow.id == str(reservation_id))
        ).scalar_one_or_none()
        if row is None:
            return None
        return self._row_to_record(row)

    def update_status(self, reservation_id: ReservationId, status: str) -> None:
        self._session.execute(
            update(ReservationRow)
            .where(ReservationRow.id == str(reservation_id))
            .values(status=status)
        )

    def find_elapsed_active(self, now: datetime, limit: int = 100) -> list[ReservationRecord]:
        """Return ACTIVE reservations past their valid_until, capped at limit.

        Uses FOR UPDATE SKIP LOCKED so concurrent Expiry Workers don't
        process the same rows simultaneously.
        """
        rows = self._session.execute(
            select(ReservationRow)
            .where(ReservationRow.status == "ACTIVE")
            .where(ReservationRow.valid_until <= now)
            .order_by(ReservationRow.valid_until)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).scalars().all()
        return [self._row_to_record(r) for r in rows]

    def _row_to_record(self, row: ReservationRow) -> ReservationRecord:
        return ReservationRecord(
            id=ReservationId(row.id),
            quote_id=QuoteId(row.quote_id),
            item_id=ItemId(row.item_id),
            gold_price_id=GoldPriceId(row.gold_price_id),
            locked_rate_per_gram_24k=Decimal(str(row.locked_rate_per_gram_24k)),
            karat_rate_per_gram=Decimal(str(row.karat_rate_per_gram)),
            pricing_engine_version=row.pricing_engine_version,
            reserved_at=row.reserved_at,
            valid_until=row.valid_until,
            status=row.status,
            customer_phone=getattr(row, "customer_phone", None),
        )


class SQLAlchemyReservationOutbox:
    def __init__(self, session: Session) -> None:
        self._session = session

    def enqueue(self, event: DomainEvent) -> None:
        row = OutboxEventRow(
            event_id=event.event_id,
            event_type=event.event_type,
            payload=json.dumps(asdict(event), default=_json_default),
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(row)
