"""End-to-end test: PaymentService → FakeGateway → CheckoutService.

Proves the full payment flow works with zero network calls:

    1. PaymentService.issue()
           ↓ FakePaymentGateway.initiate()
       PaymentIntent(PENDING) + PaymentIntentCreated event

    2. PaymentService.confirm()   [simulated webhook]
           ↓ FakePaymentGateway (WebhookResult passed directly)
       PaymentIntent(PAID) + PaymentReceived event

    3. CheckoutService.confirm()
       ReservationRecord(COMPLETED) + ReservationConfirmed event

This test is the contract between the Payment domain and the Reservation
domain. If it fails, a domain-level invariant is broken — not an
infrastructure issue.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from yasargold_domain.orders.events import OrderCreated
from yasargold_domain.orders.testing import FakeCheckoutUnitOfWork
from yasargold_domain.payment.events import (
    DomainEvent,
    PaymentIntentCreated,
    PaymentReceived,
)
from yasargold_domain.payment.gateway import WebhookResult
from yasargold_domain.payment.intent import PaymentIntent, PaymentStatus
from yasargold_domain.payment.service import PaymentService
from yasargold_domain.payment.testing import FakePaymentGateway
from yasargold_domain.reservation.checkout_service import CheckoutService
from yasargold_domain.reservation.events import ReservationConfirmed
from yasargold_domain.reservation.repository import ReservationRecord
from yasargold_domain.shared.identifiers import (
    GoldPriceId,
    ItemId,
    PaymentIntentId,
    QuoteId,
    ReservationId,
)

# ---------------------------------------------------------------------------
# Shared test constants
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 7, 13, 14, 0, 0, tzinfo=timezone.utc)
_RES_ID = ReservationId("res_e2e_test_001")
_AMOUNT = Decimal("5500.00")
_CURRENCY = "SAR"
_CALLBACK = "https://commerce.yasargold.com/webhooks/payment"
_VALID_UNTIL = _NOW + timedelta(minutes=15)

# ---------------------------------------------------------------------------
# Stubs — minimal in-memory implementations, shared across both UoWs
# ---------------------------------------------------------------------------

@dataclass
class _StubPaymentRepo:
    intents: dict[str, PaymentIntent] = field(default_factory=dict)

    def save(self, intent: PaymentIntent) -> None:
        self.intents[str(intent.id)] = intent
        if intent.provider_reference:
            self.intents[f"ref:{intent.provider_reference}"] = intent

    def get(self, intent_id: PaymentIntentId) -> PaymentIntent | None:
        return self.intents.get(str(intent_id))

    def find_by_provider_reference(self, ref: str) -> PaymentIntent | None:
        return self.intents.get(f"ref:{ref}")


@dataclass
class _StubOutbox:
    events: list[DomainEvent] = field(default_factory=list)

    def enqueue(self, event: DomainEvent) -> None:
        self.events.append(event)


@dataclass
class _StubPaymentUow:
    repository: _StubPaymentRepo = field(default_factory=_StubPaymentRepo)
    outbox: _StubOutbox = field(default_factory=_StubOutbox)

    def __enter__(self) -> _StubPaymentUow:
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Helper — seed an ACTIVE reservation
# ---------------------------------------------------------------------------

def _seed_active_reservation(uow: FakeCheckoutUnitOfWork) -> ReservationRecord:
    record = ReservationRecord(
        id=_RES_ID,
        quote_id=QuoteId("qt_e2e_test_001"),
        item_id=ItemId(42),
        gold_price_id=GoldPriceId(18452),
        locked_rate_per_gram_24k=Decimal("230.00"),
        karat_rate_per_gram=Decimal("193.125"),
        pricing_engine_version="v1",
        reserved_at=_NOW - timedelta(minutes=5),
        valid_until=_VALID_UNTIL,
        status="ACTIVE",
    )
    uow.reservation_repository.save_reservation(record)
    return record


# ---------------------------------------------------------------------------
# Step 1 — PaymentService.issue()
# ---------------------------------------------------------------------------

class TestIssueStep:
    def test_issue_creates_pending_intent(self) -> None:
        gateway = FakePaymentGateway()
        svc = PaymentService(gateway)
        payment_uow = _StubPaymentUow()

        intent, _ = svc.issue(_RES_ID, _AMOUNT, _CURRENCY, _VALID_UNTIL, _CALLBACK, payment_uow, now=_NOW)

        assert intent.status == PaymentStatus.PENDING
        assert intent.reservation_id == _RES_ID
        assert intent.amount == _AMOUNT

    def test_issue_returns_gateway_checkout_url(self) -> None:
        gateway = FakePaymentGateway(checkout_url="https://pay.fake/checkout/xyz")
        svc = PaymentService(gateway)
        payment_uow = _StubPaymentUow()

        _, url = svc.issue(_RES_ID, _AMOUNT, _CURRENCY, _VALID_UNTIL, _CALLBACK, payment_uow, now=_NOW)

        assert url == "https://pay.fake/checkout/xyz"

    def test_issue_enqueues_payment_intent_created(self) -> None:
        gateway = FakePaymentGateway()
        svc = PaymentService(gateway)
        payment_uow = _StubPaymentUow()

        svc.issue(_RES_ID, _AMOUNT, _CURRENCY, _VALID_UNTIL, _CALLBACK, payment_uow, now=_NOW)

        assert len(payment_uow.outbox.events) == 1
        assert isinstance(payment_uow.outbox.events[0], PaymentIntentCreated)

    def test_fake_gateway_called_once(self) -> None:
        gateway = FakePaymentGateway()
        svc = PaymentService(gateway)
        payment_uow = _StubPaymentUow()

        svc.issue(_RES_ID, _AMOUNT, _CURRENCY, _VALID_UNTIL, _CALLBACK, payment_uow, now=_NOW)

        assert gateway.initiate_count == 1


# ---------------------------------------------------------------------------
# Step 2 — PaymentService.confirm() on successful webhook
# ---------------------------------------------------------------------------

class TestConfirmStep:
    def _run_issue(self, gateway: FakePaymentGateway, payment_uow: _StubPaymentUow) -> PaymentIntent:
        svc = PaymentService(gateway)
        intent, _ = svc.issue(_RES_ID, _AMOUNT, _CURRENCY, _VALID_UNTIL, _CALLBACK, payment_uow, now=_NOW)
        return intent

    def _paid_webhook(self, provider_reference: str) -> WebhookResult:
        return WebhookResult(
            provider_reference=provider_reference,
            outcome="paid",
            paid_at=_NOW,
            failure_reason=None,
        )

    def test_confirm_transitions_to_paid(self) -> None:
        gateway = FakePaymentGateway()
        payment_uow = _StubPaymentUow()
        intent = self._run_issue(gateway, payment_uow)

        svc = PaymentService(gateway)
        result = svc.confirm(self._paid_webhook(intent.provider_reference), payment_uow, now=_NOW)

        assert result.status == PaymentStatus.PAID

    def test_confirm_enqueues_payment_received(self) -> None:
        gateway = FakePaymentGateway()
        payment_uow = _StubPaymentUow()
        intent = self._run_issue(gateway, payment_uow)

        PaymentService(gateway).confirm(self._paid_webhook(intent.provider_reference), payment_uow, now=_NOW)

        received_events = [e for e in payment_uow.outbox.events if isinstance(e, PaymentReceived)]
        assert len(received_events) == 1
        assert received_events[0].reservation_id == _RES_ID

    def test_paid_intent_can_confirm(self) -> None:
        """PaymentIntent.can_confirm() is the signal to call CheckoutService."""
        gateway = FakePaymentGateway()
        payment_uow = _StubPaymentUow()
        intent = self._run_issue(gateway, payment_uow)

        result = PaymentService(gateway).confirm(
            self._paid_webhook(intent.provider_reference), payment_uow, now=_NOW
        )

        assert result.can_confirm()


# ---------------------------------------------------------------------------
# Step 3 — CheckoutService.confirm() driven by PaymentReceived
# ---------------------------------------------------------------------------

class TestCheckoutStep:
    def _run_payment_chain(
        self,
    ) -> tuple[PaymentIntent, PaymentIntent, FakeCheckoutUnitOfWork, FakePaymentGateway, _StubPaymentUow]:
        gateway = FakePaymentGateway()
        payment_uow = _StubPaymentUow()
        checkout_uow = FakeCheckoutUnitOfWork()
        _seed_active_reservation(checkout_uow)

        svc = PaymentService(gateway)
        intent, _ = svc.issue(_RES_ID, _AMOUNT, _CURRENCY, _VALID_UNTIL, _CALLBACK, payment_uow, now=_NOW)
        paid_intent = svc.confirm(
            WebhookResult(intent.provider_reference, "paid", _NOW, None),
            payment_uow, now=_NOW,
        )
        return intent, paid_intent, checkout_uow, gateway, payment_uow

    def test_checkout_completes_reservation(self) -> None:
        """Full chain: issue → confirm → CheckoutService.confirm()."""
        intent, paid_intent, checkout_uow, gateway, _ = self._run_payment_chain()
        assert paid_intent.can_confirm()

        reservation, order = CheckoutService().confirm(
            reservation_id=_RES_ID,
            payment_intent_id=paid_intent.id,
            amount=_AMOUNT,
            currency=_CURRENCY,
            uow=checkout_uow,
            now=_NOW,
        )
        assert reservation.status == "COMPLETED"

    def test_checkout_creates_order(self) -> None:
        """CheckoutService creates an Order when confirming checkout."""
        _, paid_intent, checkout_uow, _, _ = self._run_payment_chain()

        _, order = CheckoutService().confirm(
            reservation_id=_RES_ID,
            payment_intent_id=paid_intent.id,
            amount=_AMOUNT,
            currency=_CURRENCY,
            uow=checkout_uow,
            now=_NOW,
        )
        assert order is not None
        assert order.payment_intent_id == paid_intent.id

    def test_checkout_enqueues_reservation_confirmed(self) -> None:
        """ReservationConfirmed event must fire after the full chain."""
        _, paid_intent, checkout_uow, _, _ = self._run_payment_chain()

        CheckoutService().confirm(
            reservation_id=_RES_ID,
            payment_intent_id=paid_intent.id,
            amount=_AMOUNT,
            currency=_CURRENCY,
            uow=checkout_uow,
            now=_NOW,
        )

        confirmed = [e for e in checkout_uow.outbox.events if isinstance(e, ReservationConfirmed)]
        assert len(confirmed) == 1

    def test_reservation_confirmed_carries_payment_intent_id(self) -> None:
        """ReservationConfirmed.payment_intent_id links to the PaymentIntent."""
        _, paid_intent, checkout_uow, _, _ = self._run_payment_chain()

        CheckoutService().confirm(
            reservation_id=_RES_ID,
            payment_intent_id=paid_intent.id,
            amount=_AMOUNT,
            currency=_CURRENCY,
            uow=checkout_uow,
            now=_NOW,
        )

        event = next(e for e in checkout_uow.outbox.events if isinstance(e, ReservationConfirmed))
        assert event.payment_intent_id == paid_intent.id

    def test_checkout_enqueues_order_created(self) -> None:
        """OrderCreated event fires as part of the checkout chain."""
        _, paid_intent, checkout_uow, _, _ = self._run_payment_chain()

        CheckoutService().confirm(
            reservation_id=_RES_ID,
            payment_intent_id=paid_intent.id,
            amount=_AMOUNT,
            currency=_CURRENCY,
            uow=checkout_uow,
            now=_NOW,
        )

        order_events = [e for e in checkout_uow.outbox.events if isinstance(e, OrderCreated)]
        assert len(order_events) == 1

    def test_full_chain_zero_network_calls(self) -> None:
        """FakeGateway never makes a network call — this test must pass offline."""
        intent, paid_intent, checkout_uow, gateway, _ = self._run_payment_chain()

        reservation, order = CheckoutService().confirm(
            reservation_id=_RES_ID,
            payment_intent_id=paid_intent.id,
            amount=_AMOUNT,
            currency=_CURRENCY,
            uow=checkout_uow,
            now=_NOW,
        )

        assert intent.status == PaymentStatus.PENDING
        assert paid_intent.status == PaymentStatus.PAID
        assert reservation.status == "COMPLETED"
        assert order is not None
        assert gateway.initiate_count == 1
        assert gateway.parse_count == 0
