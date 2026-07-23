"""ERPSyncWorker — consumes OrderCreated events and syncs them into ERP.

Polling pattern:
    Reads outbox_events WHERE event_type = 'OrderCreated'
                          AND erp_synced_at IS NULL
    For each event:
        1. Parse OrderCreated payload (order_id, item_id, amount, currency)
        2. POST /api/internal/online-orders on the ERP server
        3. Mark erp_synced_at = now

Cursor mechanism: erp_synced_at on outbox_events.
This makes ERPSyncWorker independent of the OutboxWorker cursor (published_at)
and the NotificationWorker cursor (notification_dispatched_at). Each worker
drains its own view of the same table.

Delivery guarantee: at-least-once.
If the worker crashes after the ERP call but before marking erp_synced_at,
the event is reprocessed. The ERP endpoint is idempotent on commerce_order_id —
it returns 200 {"status": "already_processed"} on duplicates. No double invoices.

INV-4 residual risk: the protection window = time between payment_confirmation
and this worker consuming OrderCreated. SLO: P95 erp_sync_lag ≤ 30s.
Alert: erp_sync_lag_seconds P95 > 30s → incident (see ADR-016).
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from yasargold_commerce.infra.reservation_orm import OutboxEventRow
from yasargold_commerce.metrics import ERP_SYNC_ERRORS, ERP_SYNC_LAG_SECONDS, ERP_SYNC_SUCCESS

log = logging.getLogger(__name__)


class ERPSyncWorker:
    """Polls outbox_events for unprocessed OrderCreated events and syncs to ERP.

    Args:
        session_factory: SQLAlchemy sessionmaker — one session per tick.
        erp_base_url:    Base URL of the ERP Flask server
                         (e.g. "http://localhost:5000").
        internal_secret: Value of ERP_INTERNAL_SECRET — sent as X-Internal-Secret.
        batch_size:      Events processed per tick.
        http_timeout:    Seconds to wait for the ERP endpoint to respond.
    """

    def __init__(
        self,
        session_factory: sessionmaker,
        erp_base_url: str | None = None,
        internal_secret: str | None = None,
        batch_size: int = 50,
        http_timeout: float = 10.0,
    ) -> None:
        self._factory = session_factory
        self._erp_base_url = (erp_base_url or os.environ.get("ERP_BASE_URL", "")).rstrip("/")
        self._secret = internal_secret or os.environ.get("ERP_INTERNAL_SECRET", "")
        self._batch_size = batch_size
        self._timeout = http_timeout

    def run_once(self, batch_size: int | None = None) -> int:
        """Process one batch. Returns count synced."""
        limit = batch_size or self._batch_size
        session: Session = self._factory()
        try:
            rows = session.execute(
                select(OutboxEventRow)
                .where(OutboxEventRow.event_type == "OrderCreated")
                .where(OutboxEventRow.erp_synced_at.is_(None))
                .order_by(OutboxEventRow.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).scalars().all()

            if not rows:
                return 0

            synced_ids: list[int] = []
            now = datetime.now(timezone.utc)  # clock-guard: boundary

            for row in rows:
                try:
                    self._sync_event(row)
                    synced_ids.append(row.id)
                    lag = (now - row.created_at.replace(tzinfo=timezone.utc) if row.created_at.tzinfo is None else now - row.created_at).total_seconds()
                    ERP_SYNC_LAG_SECONDS.observe(lag)
                    ERP_SYNC_SUCCESS.inc()
                except Exception:
                    log.exception("erp_sync_worker: failed for outbox_id=%s", row.id)
                    ERP_SYNC_ERRORS.inc()

            if synced_ids:
                session.execute(
                    update(OutboxEventRow)
                    .where(OutboxEventRow.id.in_(synced_ids))
                    .values(erp_synced_at=now)
                )
                session.commit()

            log.info("erp_sync_worker: synced %d / %d events", len(synced_ids), len(rows))
            return len(synced_ids)

        except Exception:
            session.rollback()
            log.exception("erp_sync_worker: batch failed, will retry next tick")
            return 0
        finally:
            session.close()

    def _sync_event(self, row: OutboxEventRow) -> None:
        """Parse OrderCreated payload and POST to ERP internal endpoint."""
        payload = json.loads(row.payload)
        body = {
            "order_id": payload["order_id"],
            "item_id": payload["item_id"],
            "amount": str(payload["amount"]),
            "currency": payload.get("currency", "SAR"),
        }
        url = f"{self._erp_base_url}/api/internal/online-orders"
        response = httpx.post(
            url,
            json=body,
            headers={"X-Internal-Secret": self._secret},
            timeout=self._timeout,
        )
        if response.status_code in (200, 201):
            return
        # 409 = out of stock — log and skip (do not retry forever).
        if response.status_code == 409:
            log.warning(
                "erp_sync_worker: ERP returned 409 for order=%s — %s",
                payload["order_id"],
                response.text,
            )
            return
        # Any other non-2xx is an error — raise so the batch handler catches it.
        response.raise_for_status()

    def run_forever(self, interval_seconds: float = 5.0) -> None:
        log.info("erp_sync_worker started (interval=%.1fs)", interval_seconds)
        while True:
            try:
                n = self.run_once()
                if n == 0:
                    time.sleep(interval_seconds)
            except KeyboardInterrupt:
                log.info("erp_sync_worker stopped")
                break
