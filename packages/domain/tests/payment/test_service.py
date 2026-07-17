"""Unit tests for PaymentService.

Covers:
  - issue():   happy path, gateway failure, event content
  - confirm(): paid webhook, failed webhook, expired intent, double-deliver,
               not found, terminal status guard

All stubs are pure Python — no DB, no HTTP, no mocking library.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from yasargold_domain.payment.events import (
    DomainEvent,
    PaymentFailed,
    PaymentIntentCreated,
    PaymentReceived,
    RefundConfirmed,
)
from yasargold_domain.payment.exceptions import (
    PaymentIntentExpiredError,
    PaymentIntentNotFoundException,
    PaymentIntentStatusError,
)
from yasargold_domain.payment.gateway import CheckoutUrl, WebhookResult
from yasargold_domain.payment.intent import PaymentIntent, PaymentStatus
from yasargold_domain.payment.service import PaymentService
from yasargold_domain.shared.identifiers import (
    PaymentFailureReason,
    PaymentIntentId,
    ReservationId,
)

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 7, 13, 14, 0, 0, tzinfo=timezone.utc)
_RES_ID = ReservationId("res_abc123")
_AMOUNT = Decimal("5500.00")
_CURRENCY = "SAR"
_CALLBACK = "https://example.com/webhook"
_PROVIDER_REF = "pay_moyasar_abc123"


@dataclass
class _StubRepo:
    intents: dict[str, PaymentIntent] = field(default_factory=dict)

    def save(self, intent: PaymentIntent) -> None:
        self.intents[str(intent.id)] = intent
        if intent.provider_reference:
            self.intents[f"ref:{intent.provider_reference}"] = intent

    def get(self, intent_id: PaymentIntentId) -> PaymentIntent | None:
        return self.intents.get(str(intent_id))

    def find_by_provider_reference(self, provider_reference: str) -> PaymentIntent | None:
        return self.intents.get(f"ref:{provider_reference}")


@dataclass
class _StubOutbox:
    events: list[DomainEvent] = field(default_factory=list)

    def enqueue(self, event: DomainEvent) -> None:
        self.events.append(event)


@dataclass
class _StubUow:
    repository: _StubRepo = field(default_factory=_StubRepo)
    outbox: _StubOutbox = field(default_factory=_StubOutbox)
    committed: bool = False

    def __enter__(self) -> _StubUow:
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        pass


@dataclass
class _StubGateway:
    provider_reference: str = _PROVIDER_REF
    checkout_url: str = "https://checkout.moyasar.com/pay/abc123"
    should_fail: bool = False

    def initiate(self, intent: PaymentIntent, callback_url: str) -> CheckoutUrl:
        if self.should_fail:
            raise RuntimeError("Gateway unavailable")
        return CheckoutUrl(url=self.checkout_url, provider_reference=self.provider_reference)

    def parse_webhook(self, payload: bytes, signature: str) -> WebhookResult:
        raise NotImplementedError


def _make_service(gateway: _StubGateway | None = None) -> PaymentService:
    return PaymentService(gateway or _StubGateway())


def _make_expires_at(minutes: int = 15) -> datetime:
    return _NOW + timedelta(minutes=minutes)


# ---------------------------------------------------------------------------
# issue() — happy path
# ---------------------------------------------------------------------------

class TestIssueHappyPath:
    def test_returns_pending_intent(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        intent, _ = svc.issue(_RES_ID, _AMOUNT, _CURRENCY, _make_expires_at(), _CALLBACK, uow, now=_NOW)
        assert intent.status == PaymentStatus.PENDING

    def test_returns_checkout_url(self) -> None:
        gateway = _StubGateway(checkout_url="https://pay.example.com/abc")
        svc = _make_service(gateway)
        uow = _StubUow()
        _, url = svc.issue(_RES_ID, _AMOUNT, _CURRENCY, _make_expires_at(), _CALLBACK, uow, now=_NOW)
        assert url == "https://pay.example.com/abc"

    def test_intent_carries_provider_reference(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        intent, _ = svc.issue(_RES_ID, _AMOUNT, _CURRENCY, _make_expires_at(), _CALLBACK, uow, now=_NOW)
        assert intent.provider_reference == _PROVIDER_REF

    def test_intent_saved_to_repository(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        intent, _ = svc.issue(_RES_ID, _AMOUNT, _CURRENCY, _make_expires_at(), _CALLBACK, uow, now=_NOW)
        assert uow.repository.get(intent.id) is not None

    def test_enqueues_payment_intent_created_event(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        svc.issue(_RES_ID, _AMOUNT, _CURRENCY, _make_expires_at(), _CALLBACK, uow, now=_NOW)
        assert len(uow.outbox.events) == 1
        assert isinstance(uow.outbox.events[0], PaymentIntentCreated)

    def test_event_carries_reservation_id(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        svc.issue(_RES_ID, _AMOUNT, _CURRENCY, _make_expires_at(), _CALLBACK, uow, now=_NOW)
        event: PaymentIntentCreated = uow.outbox.events[0]  # type: ignore[assignment]
        assert event.reservation_id == _RES_ID

    def test_event_carries_amount(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        svc.issue(_RES_ID, _AMOUNT, _CURRENCY, _make_expires_at(), _CALLBACK, uow, now=_NOW)
        event: PaymentIntentCreated = uow.outbox.events[0]  # type: ignore[assignment]
        assert event.amount == _AMOUNT

    def test_caller_controls_commit(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        svc.issue(_RES_ID, _AMOUNT, _CURRENCY, _make_expires_at(), _CALLBACK, uow, now=_NOW)
        assert not uow.committed


# ---------------------------------------------------------------------------
# issue() — gateway failure
# ---------------------------------------------------------------------------

class TestIssueGatewayFailure:
    def test_gateway_error_propagates(self) -> None:
        svc = _make_service(_StubGateway(should_fail=True))
        uow = _StubUow()
        with pytest.raises(RuntimeError, match="Gateway unavailable"):
            svc.issue(_RES_ID, _AMOUNT, _CURRENCY, _make_expires_at(), _CALLBACK, uow, now=_NOW)

    def test_nothing_saved_on_gateway_failure(self) -> None:
        svc = _make_service(_StubGateway(should_fail=True))
        uow = _StubUow()
        with pytest.raises(RuntimeError):
            svc.issue(_RES_ID, _AMOUNT, _CURRENCY, _make_expires_at(), _CALLBACK, uow, now=_NOW)
        assert len(uow.repository.intents) == 0

    def test_no_event_enqueued_on_gateway_failure(self) -> None:
        svc = _make_service(_StubGateway(should_fail=True))
        uow = _StubUow()
        with pytest.raises(RuntimeError):
            svc.issue(_RES_ID, _AMOUNT, _CURRENCY, _make_expires_at(), _CALLBACK, uow, now=_NOW)
        assert len(uow.outbox.events) == 0


# ---------------------------------------------------------------------------
# confirm() — paid webhook (happy path)
# ---------------------------------------------------------------------------

def _seed_intent(uow: _StubUow, minutes_until_expiry: int = 15) -> PaymentIntent:
    intent = PaymentIntent(
        id=PaymentIntentId("pi_test0001"),
        reservation_id=_RES_ID,
        amount=_AMOUNT,
        currency=_CURRENCY,
        status=PaymentStatus.PENDING,
        created_at=_NOW - timedelta(minutes=1),
        expires_at=_NOW + timedelta(minutes=minutes_until_expiry),
        provider_reference=_PROVIDER_REF,
    )
    uow.repository.save(intent)
    return intent


def _paid_webhook(paid_at: datetime | None = None) -> WebhookResult:
    return WebhookResult(
        provider_reference=_PROVIDER_REF,
        outcome="paid",
        paid_at=paid_at or _NOW,
        failure_reason=None,
    )


def _failed_webhook(reason: str = "card_declined") -> WebhookResult:
    return WebhookResult(
        provider_reference=_PROVIDER_REF,
        outcome="failed",
        paid_at=None,
        failure_reason=PaymentFailureReason(reason),
    )


class TestConfirmPaid:
    def test_returns_paid_intent(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        _seed_intent(uow)
        result = svc.confirm(_paid_webhook(), uow, now=_NOW)
        assert result.status == PaymentStatus.PAID

    def test_paid_at_set_from_webhook(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        _seed_intent(uow)
        paid_at = _NOW - timedelta(seconds=5)
        result = svc.confirm(_paid_webhook(paid_at=paid_at), uow, now=_NOW)
        assert result.paid_at == paid_at

    def test_intent_saved_as_paid(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        _seed_intent(uow)
        svc.confirm(_paid_webhook(), uow, now=_NOW)
        saved = uow.repository.find_by_provider_reference(_PROVIDER_REF)
        assert saved is not None and saved.status == PaymentStatus.PAID

    def test_enqueues_payment_received_event(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        _seed_intent(uow)
        svc.confirm(_paid_webhook(), uow, now=_NOW)
        assert any(isinstance(e, PaymentReceived) for e in uow.outbox.events)

    def test_event_carries_reservation_id(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        _seed_intent(uow)
        svc.confirm(_paid_webhook(), uow, now=_NOW)
        event = next(e for e in uow.outbox.events if isinstance(e, PaymentReceived))
        assert event.reservation_id == _RES_ID

    def test_caller_controls_commit(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        _seed_intent(uow)
        svc.confirm(_paid_webhook(), uow, now=_NOW)
        assert not uow.committed


# ---------------------------------------------------------------------------
# confirm() — failed webhook
# ---------------------------------------------------------------------------

class TestConfirmFailed:
    def test_returns_failed_intent(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        _seed_intent(uow)
        result = svc.confirm(_failed_webhook(), uow, now=_NOW)
        assert result.status == PaymentStatus.FAILED

    def test_failure_reason_stored(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        _seed_intent(uow)
        result = svc.confirm(_failed_webhook("insufficient_funds"), uow, now=_NOW)
        assert result.failure_reason == PaymentFailureReason("insufficient_funds")

    def test_enqueues_payment_failed_event(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        _seed_intent(uow)
        svc.confirm(_failed_webhook(), uow, now=_NOW)
        assert any(isinstance(e, PaymentFailed) for e in uow.outbox.events)


# ---------------------------------------------------------------------------
# confirm() — expired intent (paid webhook arrives after expires_at)
# ---------------------------------------------------------------------------

class TestConfirmExpiredIntent:
    def test_paid_webhook_after_expiry_raises(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        _seed_intent(uow, minutes_until_expiry=-1)
        with pytest.raises(PaymentIntentExpiredError):
            svc.confirm(_paid_webhook(), uow, now=_NOW)

    def test_expiry_error_carries_intent_id(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        _seed_intent(uow, minutes_until_expiry=-1)
        with pytest.raises(PaymentIntentExpiredError) as exc_info:
            svc.confirm(_paid_webhook(), uow, now=_NOW)
        assert exc_info.value.intent_id == "pi_test0001"

    def test_nothing_saved_on_expired_paid_webhook(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        original = _seed_intent(uow, minutes_until_expiry=-1)
        with pytest.raises(PaymentIntentExpiredError):
            svc.confirm(_paid_webhook(), uow, now=_NOW)
        saved = uow.repository.find_by_provider_reference(_PROVIDER_REF)
        assert saved is not None and saved.status == PaymentStatus.PENDING

    def test_failed_webhook_after_expiry_still_processes(self) -> None:
        """A failed webhook is always accepted — we record the failure regardless."""
        svc = _make_service()
        uow = _StubUow()
        _seed_intent(uow, minutes_until_expiry=-1)
        result = svc.confirm(_failed_webhook(), uow, now=_NOW)
        assert result.status == PaymentStatus.FAILED


# ---------------------------------------------------------------------------
# confirm() — double delivery (terminal status)
# ---------------------------------------------------------------------------

class TestConfirmDoubleDeliver:
    def _seed_paid(self, uow: _StubUow) -> None:
        intent = replace(
            _seed_intent(uow),
            status=PaymentStatus.PAID,
            paid_at=_NOW,
        )
        uow.repository.save(intent)

    def test_double_paid_webhook_raises_status_error(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        self._seed_paid(uow)
        with pytest.raises(PaymentIntentStatusError) as exc_info:
            svc.confirm(_paid_webhook(), uow, now=_NOW)
        assert exc_info.value.current_status == "PAID"

    def test_status_error_does_not_enqueue_event(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        self._seed_paid(uow)
        with pytest.raises(PaymentIntentStatusError):
            svc.confirm(_paid_webhook(), uow, now=_NOW)
        assert not any(isinstance(e, PaymentReceived) for e in uow.outbox.events)


# ---------------------------------------------------------------------------
# confirm() — not found
# ---------------------------------------------------------------------------

class TestConfirmNotFound:
    def test_unknown_reference_raises_not_found(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        webhook = WebhookResult(
            provider_reference="pay_unknown_xyz",
            outcome="paid",
            paid_at=_NOW,
            failure_reason=None,
        )
        with pytest.raises(PaymentIntentNotFoundException) as exc_info:
            svc.confirm(webhook, uow, now=_NOW)
        assert exc_info.value.provider_reference == "pay_unknown_xyz"


# ---------------------------------------------------------------------------
# mark_refund_pending() + mark_refunded() — refund lifecycle (Sprint 8)
# ---------------------------------------------------------------------------

def _make_paid_intent() -> PaymentIntent:
    """Return a minimal PAID intent for refund lifecycle tests."""
    from yasargold_domain.payment.intent import PaymentIntent
    return PaymentIntent(
        id=PaymentIntentId("pi_refund_test"),
        reservation_id=_RES_ID,
        amount=_AMOUNT,
        currency=_CURRENCY,
        status=PaymentStatus.PAID,
        created_at=_NOW,
        expires_at=_NOW + timedelta(minutes=15),
        provider_reference=_PROVIDER_REF,
        paid_at=_NOW,
    )


class TestMarkRefundPending:
    def test_transitions_paid_to_refund_pending(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        intent = _make_paid_intent()
        result = svc.mark_refund_pending(intent, uow)
        assert result.status == PaymentStatus.REFUND_PENDING

    def test_saves_updated_intent(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        intent = _make_paid_intent()
        svc.mark_refund_pending(intent, uow)
        saved = uow.repository.intents.get(str(intent.id))
        assert saved is not None
        assert saved.status == PaymentStatus.REFUND_PENDING

    def test_wrong_status_raises(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        intent = _make_paid_intent()
        # PENDING cannot transition to REFUND_PENDING
        pending_intent = replace(intent, status=PaymentStatus.PENDING)
        with pytest.raises(PaymentIntentStatusError) as exc_info:
            svc.mark_refund_pending(pending_intent, uow)
        assert exc_info.value.current_status == "PENDING"


class TestMarkRefunded:
    def _make_refund_pending(self) -> PaymentIntent:
        return replace(_make_paid_intent(), status=PaymentStatus.REFUND_PENDING)

    def test_transitions_refund_pending_to_refunded(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        intent = self._make_refund_pending()
        result = svc.mark_refunded(intent, uow, now=_NOW)
        assert result.status == PaymentStatus.REFUNDED

    def test_refunded_at_set_to_now(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        intent = self._make_refund_pending()
        result = svc.mark_refunded(intent, uow, now=_NOW)
        assert result.refunded_at == _NOW

    def test_enqueues_refund_confirmed_event(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        intent = self._make_refund_pending()
        svc.mark_refunded(intent, uow, now=_NOW)
        assert any(isinstance(e, RefundConfirmed) for e in uow.outbox.events)

    def test_refund_confirmed_carries_correct_amount(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        intent = self._make_refund_pending()
        svc.mark_refunded(intent, uow, now=_NOW)
        event = next(e for e in uow.outbox.events if isinstance(e, RefundConfirmed))
        assert event.amount == _AMOUNT

    def test_refund_confirmed_carries_refunded_at(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        intent = self._make_refund_pending()
        svc.mark_refunded(intent, uow, now=_NOW)
        event = next(e for e in uow.outbox.events if isinstance(e, RefundConfirmed))
        assert event.refunded_at == _NOW

    def test_wrong_status_raises(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        intent = _make_paid_intent()  # PAID, not REFUND_PENDING
        with pytest.raises(PaymentIntentStatusError) as exc_info:
            svc.mark_refunded(intent, uow, now=_NOW)
        assert exc_info.value.current_status == "PAID"

    def test_refunded_is_terminal(self) -> None:
        svc = _make_service()
        uow = _StubUow()
        intent = self._make_refund_pending()
        result = svc.mark_refunded(intent, uow, now=_NOW)
        assert result.status.is_terminal
