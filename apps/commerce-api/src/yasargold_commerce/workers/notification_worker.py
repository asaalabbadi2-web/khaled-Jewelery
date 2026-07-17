"""NotificationWorker — consumes OrderCreated events from the Outbox.

Polling pattern:
    Reads outbox_events WHERE event_type = 'OrderCreated'
                          AND notification_dispatched_at IS NULL
    For each event:
        1. Parse OrderCreated payload
        2. Load customer_phone from reservations table
        3. Dispatch SMS notification via NotificationService
        4. Mark notification_dispatched_at = now

Cursor mechanism: notification_dispatched_at on outbox_events.
This makes the NotificationWorker independent of the OutboxWorker cursor
(published_at) — each worker drains its own view of the table.

Delivery guarantee: at-least-once (if worker crashes between dispatch and mark,
the event is reprocessed). NotificationService records a new Notification row;
deduplication is by order_id (find_by_order_id check in dispatch_for_order).

ADR-014: provider-agnostic; real SMS adapter injected at startup.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError as SAIntegrityError
from sqlalchemy.orm import Session, sessionmaker

from yasargold_domain.notifications.channels import NotificationChannel, NotificationTemplate
from yasargold_domain.notifications.gateway import NotificationGateway
from yasargold_domain.notifications.service import NotificationService
from yasargold_domain.shared.identifiers import OrderId, ReservationId

from yasargold_commerce.infra.notification_uow import SQLAlchemyNotificationUnitOfWork
from yasargold_commerce.infra.reservation_orm import OutboxEventRow, ReservationRow

log = logging.getLogger(__name__)


class NotificationWorker:
    """Polls outbox_events for unprocessed OrderCreated events and sends notifications.

    Args:
        session_factory: SQLAlchemy sessionmaker — one session per tick.
        gateway:         NotificationGateway implementation (injected).
        batch_size:      Events processed per tick.
    """

    def __init__(
        self,
        session_factory: sessionmaker,
        gateway: NotificationGateway,
        batch_size: int = 50,
    ) -> None:
        self._factory = session_factory
        self._service = NotificationService(gateway)
        self._batch_size = batch_size

    def run_once(self, batch_size: int | None = None) -> int:
        """Process one batch. Returns count dispatched."""
        limit = batch_size or self._batch_size
        session: Session = self._factory()
        try:
            rows = session.execute(
                select(OutboxEventRow)
                .where(OutboxEventRow.event_type == "OrderCreated")
                .where(OutboxEventRow.notification_dispatched_at.is_(None))
                .order_by(OutboxEventRow.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).scalars().all()

            if not rows:
                return 0

            dispatched_ids: list[int] = []
            now = datetime.now(timezone.utc)

            for row in rows:
                try:
                    self._dispatch_for_event(session, row, now)
                    dispatched_ids.append(row.id)
                except Exception:
                    log.exception("notification_worker: failed for outbox_id=%s", row.id)

            if dispatched_ids:
                session.execute(
                    update(OutboxEventRow)
                    .where(OutboxEventRow.id.in_(dispatched_ids))
                    .values(notification_dispatched_at=now)
                )
                session.commit()

            log.info("notification_worker: dispatched %d / %d events", len(dispatched_ids), len(rows))
            return len(dispatched_ids)

        except Exception:
            session.rollback()
            log.exception("notification_worker: batch failed, will retry next tick")
            return 0
        finally:
            session.close()

    def _dispatch_for_event(self, session: Session, row: OutboxEventRow, now: datetime) -> None:
        """Parse OrderCreated payload, load customer_phone, dispatch notification."""
        payload = json.loads(row.payload)
        order_id = OrderId(payload["order_id"])
        reservation_id = ReservationId(payload["reservation_id"])

        res_row = session.execute(
            select(ReservationRow).where(ReservationRow.id == str(reservation_id))
        ).scalar_one_or_none()

        if res_row is None or not res_row.customer_phone:
            log.info(
                "notification_worker: no customer_phone for reservation=%s — skipping",
                reservation_id,
            )
            return

        uow = SQLAlchemyNotificationUnitOfWork(session)
        existing = uow.repository.find_by_order_id(order_id)
        already_sent = any(
            n.template == NotificationTemplate.ORDER_CONFIRMED
            and n.channel == NotificationChannel.SMS
            for n in existing
        )
        if already_sent:
            log.info("notification_worker: already sent ORDER_CONFIRMED SMS for order=%s", order_id)
            return

        idempotency_key = (
            f"{order_id}:{NotificationTemplate.ORDER_CONFIRMED.value}:{NotificationChannel.SMS.value}"
        )
        try:
            with uow:
                self._service.dispatch(
                    order_id=order_id,
                    channel=NotificationChannel.SMS,
                    recipient=res_row.customer_phone,
                    template=NotificationTemplate.ORDER_CONFIRMED,
                    variables={
                        "order_id": str(order_id),
                        "amount": str(payload.get("amount", "")),
                        "currency": payload.get("currency", "SAR"),
                    },
                    uow=uow,
                    now=now,
                    idempotency_key=idempotency_key,
                )
                uow.commit()
        except SAIntegrityError:
            # Race bypassed the application guard and hit the DB unique constraint.
            # Treat as already sent: return normally so the caller adds this row to
            # dispatched_ids and advances the cursor. Without this, the event would
            # requeue forever, triggering the constraint on every retry.
            log.info(
                "notification_worker: duplicate notification blocked by DB constraint "
                "for order=%s — cursor will advance",
                order_id,
            )

    def run_forever(self, interval_seconds: float = 5.0) -> None:
        log.info("notification_worker started (interval=%.1fs)", interval_seconds)
        while True:
            try:
                n = self.run_once()
                if n == 0:
                    time.sleep(interval_seconds)
            except KeyboardInterrupt:
                log.info("notification_worker stopped")
                break
