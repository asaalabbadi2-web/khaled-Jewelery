"""Reservation Expiry Worker.

Polls ACTIVE reservations past their valid_until and transitions them to EXPIRED.

This is the infrastructure wrapper around ReservationExpiryService (domain).
The domain service holds the expiry logic; this file only provides:
  - Session management
  - Scheduler integration
  - Metrics recording
  - Error isolation (one tick failure doesn't kill the process)

Usage:
    worker = ExpiryWorker(session_factory=_SessionLocal)

    # One tick:
    expired = worker.run_once()

    # Blocking loop:
    worker.run_forever(interval_seconds=60)
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from yasargold_domain.reservation.expiry_service import ReservationExpiryService
from yasargold_commerce.infra.reservation_uow import SQLAlchemyReservationUnitOfWork
from yasargold_commerce.metrics import (
    EXPIRY_WORKER_BATCH_SIZE,
    EXPIRY_WORKER_ERRORS,
    RESERVATION_LIFETIME_SECONDS,
)

log = logging.getLogger(__name__)

_expiry_service = ReservationExpiryService()


class ExpiryWorker:
    """Ticks through elapsed ACTIVE reservations and expires them.

    Args:
        session_factory: SQLAlchemy sessionmaker.
        batch_size:      Max reservations to expire per tick.
    """

    def __init__(self, session_factory: sessionmaker, batch_size: int = 100) -> None:
        self._factory = session_factory
        self._batch_size = batch_size

    def run_once(self) -> int:
        """Expire one batch of elapsed reservations.

        Returns count of reservations expired this tick.
        Opens its own session — does NOT share with request sessions.
        """
        session = self._factory()
        try:
            uow = SQLAlchemyReservationUnitOfWork(session)
            with uow:
                now = datetime.now(timezone.utc)
                expired = _expiry_service.expire_elapsed(uow, now=now, limit=self._batch_size)
                uow.commit()

            for record in expired:
                reserved_at = record.reserved_at
                if reserved_at.tzinfo is None:
                    reserved_at = reserved_at.replace(tzinfo=timezone.utc)
                lifetime = (now - reserved_at).total_seconds()
                RESERVATION_LIFETIME_SECONDS.labels(outcome="expired").observe(lifetime)

            count = len(expired)
            EXPIRY_WORKER_BATCH_SIZE.observe(count)
            if count:
                log.info("expiry: expired %d reservations", count)
            return count

        except Exception:
            EXPIRY_WORKER_ERRORS.inc()
            log.exception("expiry: tick failed, will retry next tick")
            return 0
        finally:
            session.close()

    def run_forever(self, interval_seconds: float = 60.0) -> None:
        """Blocking loop — run in a dedicated thread or process."""
        log.info("expiry worker started (interval=%.0fs)", interval_seconds)
        while True:
            try:
                self.run_once()
                time.sleep(interval_seconds)
            except KeyboardInterrupt:
                log.info("expiry worker stopped")
                break
