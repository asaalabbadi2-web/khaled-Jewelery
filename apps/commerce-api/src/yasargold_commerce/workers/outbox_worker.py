"""Transactional Outbox Worker.

Polls the `outbox_events` table for unpublished events, publishes them
via the injected `publish_fn`, and marks each as published.

Design:
  - At-least-once delivery: if the worker crashes after publish but before
    UPDATE, the event is re-processed next tick. Consumers must deduplicate
    on event.event_id (UUID).
  - One transaction per batch: all UPDATEs in a batch commit together.
    If publication of event N fails, the entire batch is not marked as
    published (they'll be retried next tick).
  - Pluggable publish_fn: today it can be an HTTP POST to a webhook, a Kafka
    producer, or SNS publish. The worker never knows the transport.

Usage:
    from yasargold_commerce.workers.outbox_worker import OutboxWorker, run_once

    def my_publisher(event_type: str, payload: str) -> None:
        kafka_producer.send(event_type, payload.encode())

    worker = OutboxWorker(session_factory=_SessionLocal, publish_fn=my_publisher)

    # In a scheduler tick:
    published = worker.run_once(batch_size=50)

    # Or as a blocking loop (for foreground process):
    worker.run_forever(interval_seconds=5)
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from yasargold_commerce.infra.reservation_orm import OutboxEventRow
from yasargold_commerce.metrics import (
    OUTBOX_BATCH_SIZE,
    OUTBOX_EVENTS_PENDING,
    OUTBOX_PUBLISH_DURATION,
    OUTBOX_WORKER_ERRORS,
)

log = logging.getLogger(__name__)

PublishFn = Callable[[str, str], None]
"""Signature: publish_fn(event_type: str, payload_json: str) -> None"""


class OutboxWorker:
    """Polls and drains the outbox_events table.

    Args:
        session_factory: SQLAlchemy sessionmaker — creates one session per tick.
        publish_fn:      Called for each event. Must raise on failure.
                         The worker treats any exception as a publish failure
                         and stops the batch (events will be retried next tick).
    """

    def __init__(
        self,
        session_factory: sessionmaker,
        publish_fn: PublishFn,
        batch_size: int = 50,
    ) -> None:
        self._factory = session_factory
        self._publish = publish_fn
        self._batch_size = batch_size

    def run_once(self, batch_size: int | None = None) -> int:
        """Process one batch of unpublished events.

        Returns the number of events published in this tick.
        Opens its own session — does NOT share with request sessions.
        """
        limit = batch_size or self._batch_size
        session: Session = self._factory()
        try:
            rows = session.execute(
                select(OutboxEventRow)
                .where(OutboxEventRow.published_at.is_(None))
                .order_by(OutboxEventRow.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)  # concurrent-safe: skip rows locked by another worker
            ).scalars().all()

            # Update pending gauge before processing
            pending = session.execute(
                select(func.count()).where(OutboxEventRow.published_at.is_(None))
            ).scalar_one()
            OUTBOX_EVENTS_PENDING.set(pending)

            if not rows:
                return 0

            published_ids: list[int] = []
            now = datetime.now(timezone.utc)  # clock-guard: boundary

            for row in rows:
                with OUTBOX_PUBLISH_DURATION.time():
                    self._publish(row.event_type, row.payload)
                published_ids.append(row.id)

            session.execute(
                update(OutboxEventRow)
                .where(OutboxEventRow.id.in_(published_ids))
                .values(published_at=now)
            )
            session.commit()

            OUTBOX_BATCH_SIZE.observe(len(published_ids))
            OUTBOX_EVENTS_PENDING.dec(len(published_ids))
            log.info("outbox: published %d events (%d still pending)", len(published_ids), pending - len(published_ids))
            return len(published_ids)

        except Exception:
            session.rollback()
            OUTBOX_WORKER_ERRORS.inc()
            log.exception("outbox: batch failed, will retry next tick")
            return 0
        finally:
            session.close()

    def run_forever(self, interval_seconds: float = 5.0) -> None:
        """Blocking loop — intended for a dedicated process or thread.

        Stops only on KeyboardInterrupt or SIGTERM.
        """
        log.info("outbox worker started (interval=%.1fs)", interval_seconds)
        while True:
            try:
                n = self.run_once()
                if n == 0:
                    time.sleep(interval_seconds)
                # If we published a full batch, run again immediately
                # (there may be more pending events).
            except KeyboardInterrupt:
                log.info("outbox worker stopped")
                break
