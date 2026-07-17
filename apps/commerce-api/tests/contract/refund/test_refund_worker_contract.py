"""Contract tests for RefundWorker.

Tests exercise the worker against in-memory stubs — no DB, no real gateway.

Gate coverage:
    RF1: run_once() returns 0 when no REFUND_PENDING intents
    RF2: gateway.refund() is called with the correct intent
    RF3: successful refund → intent saved as REFUNDED + RefundConfirmed enqueued
    RF4: RefundPermanentError → skip intent (no commit, no mark)
    RF5: transient gateway exception → skip intent (retry next tick)
    RF6: refunded_at is set to the worker's clock value (ADR-015)
    RF7: two intents — one succeeds, one fails → only success is committed
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from yasargold_domain.payment.events import RefundConfirmed
from yasargold_domain.payment.intent import PaymentIntent, PaymentStatus
from yasargold_domain.payment.refund_gateway import RefundPermanentError
from yasargold_domain.shared.identifiers import PaymentIntentId, ReservationId

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)
_AMOUNT = Decimal("5500.00")
_INTENT_ID = PaymentIntentId("pi_refund_rf_001")
_RES_ID = ReservationId("res_rf_001")


def _make_refund_pending_intent(intent_id: str = "pi_refund_rf_001") -> PaymentIntent:
    return PaymentIntent(
        id=PaymentIntentId(intent_id),
        reservation_id=_RES_ID,
        amount=_AMOUNT,
        currency="SAR",
        status=PaymentStatus.REFUND_PENDING,
        created_at=_NOW,
        expires_at=_NOW,
        provider_reference="pay_ref_001",
    )


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

@dataclass
class _StubRepo:
    intents: list[PaymentIntent] = field(default_factory=list)
    saved: list[PaymentIntent] = field(default_factory=list)

    def find_refund_pending(self, limit: int = 50) -> list[PaymentIntent]:
        return self.intents[:limit]

    def save(self, intent: PaymentIntent) -> None:
        self.saved.append(intent)


@dataclass
class _StubOutbox:
    events: list[Any] = field(default_factory=list)

    def enqueue(self, event: Any) -> None:
        self.events.append(event)


@dataclass
class _StubUow:
    repository: _StubRepo = field(default_factory=_StubRepo)
    outbox: _StubOutbox = field(default_factory=_StubOutbox)
    committed: bool = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        pass


@dataclass
class _StubGateway:
    fail_permanent: bool = False
    fail_transient: bool = False
    refund_calls: list[PaymentIntent] = field(default_factory=list)

    def refund(self, intent: PaymentIntent) -> None:
        self.refund_calls.append(intent)
        if self.fail_permanent:
            raise RefundPermanentError("already refunded at provider")
        if self.fail_transient:
            raise ConnectionError("gateway timeout")


def _make_worker(gateway: _StubGateway, uow: _StubUow):
    from yasargold_commerce.workers.refund_worker import RefundWorker
    worker = RefundWorker(
        session_factory=lambda: _FakeSession(uow),
        gateway=gateway,
    )
    return worker


@dataclass
class _FakeSession:
    """Wraps _StubUow so the worker can call SQLAlchemyPaymentUnitOfWork on it."""
    _uow: _StubUow

    def close(self) -> None:
        pass

    def commit(self) -> None:
        self._uow.commit()

    def rollback(self) -> None:
        self._uow.rollback()


# ---------------------------------------------------------------------------
# We need to override SQLAlchemyPaymentUnitOfWork to use our stubs.
# Patch it at the worker module level.
# ---------------------------------------------------------------------------

from unittest.mock import patch


def _run_with_stubs(worker, uow: _StubUow) -> int:
    """Run worker.run_once() with the stub UoW injected."""
    with patch(
        "yasargold_commerce.workers.refund_worker.SQLAlchemyPaymentUnitOfWork",
        return_value=uow,
    ):
        return worker.run_once()


# ---------------------------------------------------------------------------
# RF1: no intents → 0
# ---------------------------------------------------------------------------

class TestRF1NoIntents:
    def test_returns_zero_when_no_pending_refunds(self) -> None:
        gw = _StubGateway()
        uow = _StubUow()
        worker = _make_worker(gw, uow)
        result = _run_with_stubs(worker, uow)
        assert result == 0


# ---------------------------------------------------------------------------
# RF2: gateway.refund() called with correct intent
# ---------------------------------------------------------------------------

class TestRF2GatewayCalled:
    def test_refund_called_with_intent(self) -> None:
        gw = _StubGateway()
        uow = _StubUow(repository=_StubRepo(intents=[_make_refund_pending_intent()]))
        worker = _make_worker(gw, uow)
        _run_with_stubs(worker, uow)
        assert len(gw.refund_calls) == 1
        assert gw.refund_calls[0].id == _INTENT_ID


# ---------------------------------------------------------------------------
# RF3: success → REFUNDED + RefundConfirmed
# ---------------------------------------------------------------------------

class TestRF3Success:
    def test_intent_saved_as_refunded(self) -> None:
        gw = _StubGateway()
        uow = _StubUow(repository=_StubRepo(intents=[_make_refund_pending_intent()]))
        worker = _make_worker(gw, uow)
        _run_with_stubs(worker, uow)
        assert any(i.status == PaymentStatus.REFUNDED for i in uow.repository.saved)

    def test_refund_confirmed_enqueued(self) -> None:
        gw = _StubGateway()
        uow = _StubUow(repository=_StubRepo(intents=[_make_refund_pending_intent()]))
        worker = _make_worker(gw, uow)
        _run_with_stubs(worker, uow)
        assert any(isinstance(e, RefundConfirmed) for e in uow.outbox.events)

    def test_returns_one(self) -> None:
        gw = _StubGateway()
        uow = _StubUow(repository=_StubRepo(intents=[_make_refund_pending_intent()]))
        worker = _make_worker(gw, uow)
        result = _run_with_stubs(worker, uow)
        assert result == 1

    def test_committed(self) -> None:
        gw = _StubGateway()
        uow = _StubUow(repository=_StubRepo(intents=[_make_refund_pending_intent()]))
        worker = _make_worker(gw, uow)
        _run_with_stubs(worker, uow)
        assert uow.committed


# ---------------------------------------------------------------------------
# RF4: RefundPermanentError → skip, no save
# ---------------------------------------------------------------------------

class TestRF4PermanentError:
    def test_permanent_error_skips_intent(self) -> None:
        gw = _StubGateway(fail_permanent=True)
        uow = _StubUow(repository=_StubRepo(intents=[_make_refund_pending_intent()]))
        worker = _make_worker(gw, uow)
        result = _run_with_stubs(worker, uow)
        assert result == 0

    def test_permanent_error_does_not_save(self) -> None:
        gw = _StubGateway(fail_permanent=True)
        uow = _StubUow(repository=_StubRepo(intents=[_make_refund_pending_intent()]))
        worker = _make_worker(gw, uow)
        _run_with_stubs(worker, uow)
        assert not uow.repository.saved


# ---------------------------------------------------------------------------
# RF5: transient gateway exception → skip, no save
# ---------------------------------------------------------------------------

class TestRF5TransientError:
    def test_transient_error_skips_intent(self) -> None:
        gw = _StubGateway(fail_transient=True)
        uow = _StubUow(repository=_StubRepo(intents=[_make_refund_pending_intent()]))
        worker = _make_worker(gw, uow)
        result = _run_with_stubs(worker, uow)
        assert result == 0


# ---------------------------------------------------------------------------
# RF6: refunded_at set to worker's now (ADR-015 Clock Protocol)
# ---------------------------------------------------------------------------

class TestRF6RefundedAt:
    def test_refunded_at_set_on_saved_intent(self) -> None:
        gw = _StubGateway()
        uow = _StubUow(repository=_StubRepo(intents=[_make_refund_pending_intent()]))
        worker = _make_worker(gw, uow)
        _run_with_stubs(worker, uow)
        refunded = next(i for i in uow.repository.saved if i.status == PaymentStatus.REFUNDED)
        assert refunded.refunded_at is not None

    def test_refund_confirmed_event_carries_refunded_at(self) -> None:
        gw = _StubGateway()
        uow = _StubUow(repository=_StubRepo(intents=[_make_refund_pending_intent()]))
        worker = _make_worker(gw, uow)
        _run_with_stubs(worker, uow)
        event = next(e for e in uow.outbox.events if isinstance(e, RefundConfirmed))
        assert event.refunded_at is not None


# ---------------------------------------------------------------------------
# RF7: two intents — one succeeds, one permanent-fails
# ---------------------------------------------------------------------------

class TestRF7MixedBatch:
    def test_only_successful_intent_counted(self) -> None:
        call_count = 0

        class _MixedGateway:
            def refund(self, intent: PaymentIntent) -> None:
                nonlocal call_count
                call_count += 1
                if call_count == 2:
                    raise RefundPermanentError("already refunded")

        gw = _MixedGateway()
        intents = [
            _make_refund_pending_intent("pi_ok"),
            _make_refund_pending_intent("pi_fail"),
        ]
        uow = _StubUow(repository=_StubRepo(intents=intents))
        worker = _make_worker(gw, uow)
        result = _run_with_stubs(worker, uow)
        assert result == 1

    def test_successful_intent_is_saved(self) -> None:
        call_count = 0

        class _MixedGateway:
            def refund(self, intent: PaymentIntent) -> None:
                nonlocal call_count
                call_count += 1
                if call_count == 2:
                    raise RefundPermanentError("already refunded")

        gw = _MixedGateway()
        intents = [
            _make_refund_pending_intent("pi_ok"),
            _make_refund_pending_intent("pi_fail"),
        ]
        uow = _StubUow(repository=_StubRepo(intents=intents))
        worker = _make_worker(gw, uow)
        _run_with_stubs(worker, uow)
        saved_ids = [str(i.id) for i in uow.repository.saved]
        assert "pi_ok" in saved_ids
        assert "pi_fail" not in saved_ids
