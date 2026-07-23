#!/usr/bin/env python3
"""Commerce worker launcher for local/staging environments.

Starts all background workers in daemon threads so a single worker failure
does not take down the others.  In production each worker runs in its own
container with its own restart policy — this launcher exists ONLY for the
local staging compose (see docker-compose.local.yml).

Workers started:
  ExpiryWorker       — expires elapsed ACTIVE reservations (30 s interval)
  OutboxWorker       — publishes outbox_events to ERP sync (5 s interval)
  ERPSyncWorker      — delivers OrderCreated to ERP internal API (30 s)
  RefundWorker       — processes REFUND_PENDING payment intents (60 s)
  NotificationWorker — dispatches SMS for OrderCreated events (60 s)
  ReconciliationWorker — compares Commerce orders vs ERP invoices (5 min)
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-30s %(levelname)s %(message)s",
)
log = logging.getLogger("run_workers")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from yasargold_commerce.infra.log_notification_gateway import LogNotificationGateway
from yasargold_commerce.infra.log_refund_gateway import LogRefundGateway
from yasargold_commerce.workers.erp_sync_worker import ERPSyncWorker
from yasargold_commerce.workers.expiry_worker import ExpiryWorker
from yasargold_commerce.workers.notification_worker import NotificationWorker
from yasargold_commerce.workers.outbox_worker import OutboxWorker
from yasargold_commerce.workers.reconciliation_worker import ReconciliationWorker
from yasargold_commerce.workers.refund_worker import RefundWorker


def _session_factory() -> sessionmaker:
    url = os.environ["DATABASE_URL"]
    engine = create_engine(url, pool_pre_ping=True, pool_size=3)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _log_publish(event_type: str, payload: str) -> None:
    log.info("outbox publish: type=%s payload_len=%d", event_type, len(payload))


def _run_forever(worker: object, interval: int) -> None:
    # Most workers have run_forever(); ReconciliationWorker only has run_once() —
    # wrap it in a polling loop so the launcher stays uniform.
    if hasattr(worker, "run_forever"):
        try:
            worker.run_forever(interval_seconds=interval)  # type: ignore[attr-defined]
        except Exception:
            log.exception("worker %s crashed", type(worker).__name__)
    else:
        while True:
            try:
                worker.run_once()  # type: ignore[attr-defined]
            except Exception:
                log.exception("worker %s tick failed", type(worker).__name__)
            time.sleep(interval)


def main() -> None:
    sf = _session_factory()

    workers = [
        (ExpiryWorker(session_factory=sf), 30),
        (OutboxWorker(session_factory=sf, publish_fn=_log_publish), 5),
        (ERPSyncWorker(session_factory=sf), 30),
        (RefundWorker(session_factory=sf, gateway=LogRefundGateway()), 60),
        (NotificationWorker(session_factory=sf, gateway=LogNotificationGateway()), 60),
        (ReconciliationWorker(session_factory=sf), 300),
    ]

    threads: list[threading.Thread] = []
    for w, interval in workers:
        t = threading.Thread(
            target=_run_forever,
            args=(w, interval),
            name=type(w).__name__,
            daemon=True,
        )
        t.start()
        threads.append(t)
        log.info("started %s (interval=%ds)", type(w).__name__, interval)

    # Keep main thread alive; exit cleanly on SIGTERM/SIGINT
    def _shutdown(sig: int, _frame: object) -> None:
        log.info("received signal %d — stopping", sig)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
