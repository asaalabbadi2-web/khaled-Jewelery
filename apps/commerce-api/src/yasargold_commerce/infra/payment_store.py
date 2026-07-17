"""SQLAlchemy implementations of PaymentIntentRepository and PaymentEventOutbox.

Both operate on the same Session so they participate in the same transaction.
The UnitOfWork (payment_uow.py) holds the session and exposes both.

save() uses merge() semantics: INSERT on first call, UPDATE on subsequent
calls for the same id. This makes it safe to call save() after both
status transitions (PENDING → PAID, PENDING → FAILED).
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from yasargold_domain.payment.intent import PaymentIntent, PaymentStatus
from yasargold_domain.payment.repository import PaymentEventOutbox
from yasargold_domain.reservation.events import DomainEvent
from yasargold_domain.shared.identifiers import (
    PaymentFailureReason,
    PaymentIntentId,
    PaymentProvider,
    ReservationId,
)

from yasargold_commerce.infra.payment_orm import PaymentIntentRow
from yasargold_commerce.infra.reservation_orm import OutboxEventRow


def _json_default(obj: object) -> str:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


class SQLAlchemyPaymentIntentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, intent: PaymentIntent) -> None:
        """INSERT or UPDATE payment_intent row for this intent."""
        existing = self._session.get(PaymentIntentRow, str(intent.id))
        if existing is None:
            row = PaymentIntentRow(
                id=str(intent.id),
                reservation_id=str(intent.reservation_id),
                amount=str(intent.amount),
                currency=intent.currency,
                status=intent.status.value,
                provider=str(intent.provider) if intent.provider else None,
                provider_reference=intent.provider_reference,
                created_at=intent.created_at,
                expires_at=intent.expires_at,
                paid_at=intent.paid_at,
                failure_reason=str(intent.failure_reason) if intent.failure_reason else None,
            )
            self._session.add(row)
        else:
            existing.status = intent.status.value
            existing.provider = str(intent.provider) if intent.provider else existing.provider
            existing.provider_reference = intent.provider_reference or existing.provider_reference
            existing.paid_at = intent.paid_at
            existing.failure_reason = (
                str(intent.failure_reason) if intent.failure_reason else None
            )
            existing.refunded_at = intent.refunded_at

    def get(self, intent_id: PaymentIntentId) -> PaymentIntent | None:
        row = self._session.get(PaymentIntentRow, str(intent_id))
        if row is None:
            return None
        return self._row_to_intent(row)

    def find_refund_pending(self, limit: int = 50) -> list[PaymentIntent]:
        """Return intents in REFUND_PENDING status, oldest first."""
        rows = self._session.execute(
            select(PaymentIntentRow)
            .where(PaymentIntentRow.status == PaymentStatus.REFUND_PENDING.value)
            .order_by(PaymentIntentRow.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).scalars().all()
        return [self._row_to_intent(row) for row in rows]

    def find_by_provider_reference(self, provider_reference: str) -> PaymentIntent | None:
        row = self._session.execute(
            select(PaymentIntentRow).where(
                PaymentIntentRow.provider_reference == provider_reference
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return self._row_to_intent(row)

    def _row_to_intent(self, row: PaymentIntentRow) -> PaymentIntent:
        return PaymentIntent(
            id=PaymentIntentId(row.id),
            reservation_id=ReservationId(row.reservation_id),
            amount=Decimal(str(row.amount)),
            currency=row.currency,
            status=PaymentStatus(row.status),
            provider=PaymentProvider(row.provider) if row.provider else None,
            provider_reference=row.provider_reference,
            created_at=row.created_at,
            expires_at=row.expires_at,
            paid_at=row.paid_at,
            failure_reason=PaymentFailureReason(row.failure_reason) if row.failure_reason else None,
            refunded_at=row.refunded_at,
        )


class SQLAlchemyPaymentOutbox:
    """Shares the outbox_events table with the reservation outbox.

    Domain events from both bounded contexts land in the same table — one
    Outbox Worker processes all events regardless of their event_type.
    """

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
