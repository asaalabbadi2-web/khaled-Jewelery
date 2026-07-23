"""RefundWorker — processes REFUND_PENDING PaymentIntents.

Polling pattern:
    Reads payment_intents WHERE status = 'REFUND_PENDING'
    For each intent:
        1. Call RefundGateway.refund(intent)
        2. Transition intent → REFUNDED (via repository + outbox in one commit)

Delivery guarantee: at-least-once.
If the worker crashes after the gateway call but before commit, the intent
stays REFUND_PENDING and is reprocessed next tick. The payment provider's
refund API must be idempotent on provider_reference (Moyasar is).

Error handling:
    RefundTransientError (or any network error) → log + skip + retry next tick.
    RefundPermanentError → log ERROR + skip (manual intervention required).

Gate A dependency: this worker must be verified end-to-end in staging
(real Moyasar sandbox credentials) before production refunds can be issued.
"""
from __future__ import annotations

import logging
import time
from dataclasses import replace
from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from yasargold_domain.payment.events import RefundConfirmed
from yasargold_domain.payment.intent import PaymentStatus
from yasargold_domain.payment.refund_gateway import RefundGateway, RefundPermanentError

from yasargold_commerce.infra.payment_uow import SQLAlchemyPaymentUnitOfWork

log = logging.getLogger(__name__)


class RefundWorker:
    """Polls for REFUND_PENDING intents and issues refunds via the gateway.

    Args:
        session_factory: SQLAlchemy sessionmaker — one session per tick.
        gateway:         RefundGateway implementation (injected).
        batch_size:      Intents processed per tick.
    """

    def __init__(
        self,
        session_factory: sessionmaker,
        gateway: RefundGateway,
        batch_size: int = 20,
    ) -> None:
        self._factory = session_factory
        self._gateway = gateway
        self._batch_size = batch_size

    def run_once(self, batch_size: int | None = None) -> int:
        """Process one batch. Returns count refunded."""
        limit = batch_size or self._batch_size
        session = self._factory()
        try:
            uow = SQLAlchemyPaymentUnitOfWork(session)
            intents = uow.repository.find_refund_pending(limit=limit)

            if not intents:
                return 0

            now = datetime.now(timezone.utc)  # clock-guard: boundary
            refunded = 0

            for intent in intents:
                # Gateway call — outside the transaction.
                try:
                    self._gateway.refund(intent)
                except RefundPermanentError:
                    log.error(
                        "refund_worker: permanent failure for intent=%s — manual action required",
                        intent.id,
                    )
                    continue
                except Exception:
                    log.exception("refund_worker: transient failure for intent=%s", intent.id)
                    continue

                # Transition to REFUNDED + emit event — in one commit.
                try:
                    updated = replace(intent, status=PaymentStatus.REFUNDED, refunded_at=now)
                    uow.repository.save(updated)
                    uow.outbox.enqueue(
                        RefundConfirmed(
                            payment_intent_id=intent.id,
                            reservation_id=intent.reservation_id,
                            amount=intent.amount,
                            currency=intent.currency,
                            refunded_at=now,
                        )
                    )
                    session.commit()
                    refunded += 1
                    log.info("refund_worker: refunded intent=%s", intent.id)
                except Exception:
                    session.rollback()
                    log.exception("refund_worker: commit failed for intent=%s", intent.id)

            return refunded

        except Exception:
            session.rollback()
            log.exception("refund_worker: batch failed")
            return 0
        finally:
            session.close()

    def run_forever(self, interval_seconds: float = 30.0) -> None:
        """Blocking loop. Runs less frequently — refunds are rare."""
        log.info("refund_worker started (interval=%.1fs)", interval_seconds)
        while True:
            try:
                n = self.run_once()
                if n == 0:
                    time.sleep(interval_seconds)
            except KeyboardInterrupt:
                log.info("refund_worker stopped")
                break
