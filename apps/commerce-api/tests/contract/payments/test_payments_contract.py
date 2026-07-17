"""Contract tests for POST /api/v1/payments and POST /api/v1/webhooks/payment.

Tests the complete vertical slice for payment capability:
  Reservation → PaymentService.issue() → FakeGateway → 201
  Webhook      → PaymentService.confirm() → CheckoutService.confirm() → 204
                                           → Order created atomically

No database, no network. All stubs injected via FastAPI dependency_overrides.

Gate coverage (matching docs/runbooks/payment_validation.md):
  Gate 1: Create PaymentIntent (happy path)
  Gate 2: Valid webhook → PAID + Order(CONFIRMED) + Reservation(COMPLETED)
  Gate 3: Duplicate webhook → 204 (idempotent)
  Gate 4: Expired reservation payment → 204 (no crash)
  Gate 5: Gateway failure → 502
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from yasargold_commerce.auth import get_customer_ref
from yasargold_commerce.db import get_db
from yasargold_commerce.main import app

_TEST_CUSTOMER_REF = "+966500000001"
from yasargold_commerce.routers.payments import (
    _get_checkout_uow,
    _get_gateway,
    _get_payment_service,
    _get_payment_uow,
    _get_reservation_service,
    _get_reservation_uow,
)
from yasargold_domain.orders.events import OrderCreated
from yasargold_domain.orders.testing import FakeCheckoutUnitOfWork
from yasargold_domain.payment.events import DomainEvent, PaymentIntentCreated, PaymentReceived
from yasargold_domain.payment.gateway import CheckoutUrl, WebhookResult
from yasargold_domain.payment.intent import PaymentIntent, PaymentStatus
from yasargold_domain.payment.service import PaymentService
from yasargold_domain.payment.testing import FakePaymentGateway
from yasargold_domain.reservation.events import ReservationConfirmed
from yasargold_domain.reservation.repository import ReservationRecord
from yasargold_domain.shared.identifiers import (
    GoldPriceId,
    ItemId,
    PaymentFailureReason,
    PaymentIntentId,
    QuoteId,
    ReservationId,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_NOW = datetime.now(timezone.utc).replace(microsecond=0)
_VALID_UNTIL = _NOW + timedelta(hours=1)
_RES_ID = ReservationId("res_contract_test_001")
_AMOUNT = Decimal("5500.00")
_PROVIDER_REF = "pay_fake_contract_001"

# ---------------------------------------------------------------------------
# Stubs — payments side
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
# Reservation service stub (Law 5 — ownership check delegated to domain service)
# ---------------------------------------------------------------------------

@dataclass
class _StubReservationService:
    """Returns a fixed record or None — controls whether ownership check passes."""

    _record: ReservationRecord | None = None

    def find_reservation_for_customer(
        self,
        reservation_id: Any,
        customer_ref: Any,
        uow: Any,
    ) -> ReservationRecord | None:
        return self._record

    def reserve(self, *a: Any, **kw: Any) -> Any:
        raise NotImplementedError


@dataclass
class _FakeResUoW:
    def __enter__(self) -> _FakeResUoW:
        return self

    def __exit__(self, *a: Any) -> None:
        pass

    def commit(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Stub DB session (returns reservation row + item for /payments)
# ---------------------------------------------------------------------------

class _StubReservationRow:
    id: str = str(_RES_ID)
    item_id: int = 42
    valid_until: datetime = _VALID_UNTIL
    reserved_at: datetime = _NOW - timedelta(minutes=5)
    status: str = "ACTIVE"
    customer_phone: str = _TEST_CUSTOMER_REF


class _StubItemRow:
    id: int = 42
    price: float = 5500.0
    stock: int = 1  # ADR-013 Condition 1: default available in ERP


class _StubResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _StubDb:
    def __init__(
        self,
        res_row: Any | None = None,
        item_row: Any | None = None,
        no_reservation: bool = False,
        no_item: bool = False,
    ) -> None:
        self._res_row = None if no_reservation else (res_row or _StubReservationRow())
        self._item_row = None if no_item else (item_row or _StubItemRow())

    def execute(self, stmt: Any) -> _StubResult:
        from yasargold_commerce.infra.reservation_orm import ReservationRow
        from yasargold_commerce.models import Item
        try:
            entity = stmt.column_descriptions[0]["entity"]
            if entity is ReservationRow:
                return _StubResult(self._res_row)
            if entity is Item:
                return _StubResult(self._item_row)
        except (AttributeError, IndexError, KeyError):
            pass
        return _StubResult(None)

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Test harness helpers
# ---------------------------------------------------------------------------

def _make_active_reservation_record() -> ReservationRecord:
    return ReservationRecord(
        id=_RES_ID,
        quote_id=QuoteId("qt_contract_test_001"),
        item_id=ItemId(42),
        gold_price_id=GoldPriceId(18452),
        locked_rate_per_gram_24k=Decimal("230.00"),
        karat_rate_per_gram=Decimal("193.125"),
        pricing_engine_version="v1",
        reserved_at=_NOW - timedelta(minutes=5),
        valid_until=_VALID_UNTIL,
        status="ACTIVE",
    )


def _make_client(
    gateway: FakePaymentGateway | None = None,
    payment_uow: _StubPaymentUow | None = None,
    checkout_uow: FakeCheckoutUnitOfWork | None = None,
    db: _StubDb | None = None,
    active_reservation: bool = True,
    no_reservation: bool = False,
) -> tuple[TestClient, _StubPaymentUow, FakeCheckoutUnitOfWork]:
    gw = gateway or FakePaymentGateway(provider_reference=_PROVIDER_REF)
    puow = payment_uow or _StubPaymentUow()
    cuow = checkout_uow or FakeCheckoutUnitOfWork()
    stub_db = db or _StubDb()

    if active_reservation:
        cuow.reservation_repository.records[str(_RES_ID)] = _make_active_reservation_record()

    # Law 5: reservation ownership check is now delegated to the domain service
    res_record = None if no_reservation else _make_active_reservation_record()
    stub_res_svc = _StubReservationService(_record=res_record)

    app.dependency_overrides[get_db] = lambda: stub_db
    app.dependency_overrides[_get_gateway] = lambda: gw
    app.dependency_overrides[_get_payment_service] = lambda: PaymentService(gw)
    app.dependency_overrides[_get_payment_uow] = lambda: puow
    app.dependency_overrides[_get_checkout_uow] = lambda: cuow
    app.dependency_overrides[_get_reservation_service] = lambda: stub_res_svc
    app.dependency_overrides[_get_reservation_uow] = lambda: _FakeResUoW()
    app.dependency_overrides[get_customer_ref] = lambda: _TEST_CUSTOMER_REF

    client = TestClient(app, raise_server_exceptions=False)
    return client, puow, cuow


def _cleanup() -> None:
    app.dependency_overrides.clear()


def _paid_webhook_body(provider_reference: str = _PROVIDER_REF) -> bytes:
    return json.dumps({
        "id": provider_reference,
        "status": "paid",
        "amount": 550000,
        "currency": "SAR",
        "paid_at": "2026-07-13T14:05:00+00:00",
        "updated_at": "2026-07-13T14:05:00+00:00",
    }).encode()


# ---------------------------------------------------------------------------
# Gate 1 — Create PaymentIntent (POST /payments)
# ---------------------------------------------------------------------------

class TestGate1CreatePaymentIntent:
    def teardown_method(self) -> None:
        _cleanup()

    def test_returns_201(self) -> None:
        client, _, _ = _make_client()
        r = client.post("/api/v1/payments", json={"reservation_id": str(_RES_ID)})
        assert r.status_code == 201

    def test_response_has_payment_intent_id(self) -> None:
        client, _, _ = _make_client()
        r = client.post("/api/v1/payments", json={"reservation_id": str(_RES_ID)})
        data = r.json()
        assert "payment_intent_id" in data
        assert data["payment_intent_id"].startswith("pi_")

    def test_response_has_checkout_url(self) -> None:
        gw = FakePaymentGateway(
            checkout_url="https://pay.fake/checkout/abc",
            provider_reference=_PROVIDER_REF,
        )
        client, _, _ = _make_client(gateway=gw)
        r = client.post("/api/v1/payments", json={"reservation_id": str(_RES_ID)})
        assert r.json()["checkout_url"] == "https://pay.fake/checkout/abc"

    def test_response_has_expires_at(self) -> None:
        client, _, _ = _make_client()
        r = client.post("/api/v1/payments", json={"reservation_id": str(_RES_ID)})
        assert "expires_at" in r.json()

    def test_intent_saved_to_repository(self) -> None:
        client, puow, _ = _make_client()
        client.post("/api/v1/payments", json={"reservation_id": str(_RES_ID)})
        assert len(puow.repository.intents) > 0

    def test_payment_intent_created_event_enqueued(self) -> None:
        client, puow, _ = _make_client()
        client.post("/api/v1/payments", json={"reservation_id": str(_RES_ID)})
        assert any(isinstance(e, PaymentIntentCreated) for e in puow.outbox.events)

    def test_missing_reservation_returns_404(self) -> None:
        client, _, _ = _make_client(no_reservation=True)
        r = client.post("/api/v1/payments", json={"reservation_id": str(_RES_ID)})
        assert r.status_code == 404

    def test_missing_item_returns_404(self) -> None:
        client, _, _ = _make_client(db=_StubDb(no_item=True))
        r = client.post("/api/v1/payments", json={"reservation_id": str(_RES_ID)})
        assert r.status_code == 404

    def test_gateway_failure_returns_502(self) -> None:
        gw = FakePaymentGateway(fail_on_initiate=True)
        client, _, _ = _make_client(gateway=gw)
        r = client.post("/api/v1/payments", json={"reservation_id": str(_RES_ID)})
        assert r.status_code == 502


# ---------------------------------------------------------------------------
# Gate 2 — Valid webhook → PAID + Order(CONFIRMED) + Reservation(COMPLETED)
# ---------------------------------------------------------------------------

class TestGate2ValidWebhook:
    def teardown_method(self) -> None:
        _cleanup()

    def _seed_pending_intent(self, puow: _StubPaymentUow) -> PaymentIntent:
        intent = PaymentIntent(
            id=PaymentIntentId("pi_gate2_test_0001"),
            reservation_id=_RES_ID,
            amount=_AMOUNT,
            currency="SAR",
            status=PaymentStatus.PENDING,
            created_at=_NOW,
            expires_at=_VALID_UNTIL,
            provider_reference=_PROVIDER_REF,
        )
        puow.repository.save(intent)
        return intent

    def test_webhook_returns_204(self) -> None:
        puow = _StubPaymentUow()
        self._seed_pending_intent(puow)
        client, _, _ = _make_client(payment_uow=puow)
        r = client.post(
            "/api/v1/webhooks/payment",
            content=_paid_webhook_body(),
            headers={"X-Moyasar-Signature": "any_sig"},
        )
        assert r.status_code == 204

    def test_intent_transitions_to_paid(self) -> None:
        puow = _StubPaymentUow()
        self._seed_pending_intent(puow)
        client, _, _ = _make_client(payment_uow=puow)
        client.post(
            "/api/v1/webhooks/payment",
            content=_paid_webhook_body(),
            headers={"X-Moyasar-Signature": "any_sig"},
        )
        saved = puow.repository.find_by_provider_reference(_PROVIDER_REF)
        assert saved is not None and saved.status == PaymentStatus.PAID

    def test_payment_received_event_enqueued(self) -> None:
        puow = _StubPaymentUow()
        self._seed_pending_intent(puow)
        client, _, _ = _make_client(payment_uow=puow)
        client.post(
            "/api/v1/webhooks/payment",
            content=_paid_webhook_body(),
            headers={"X-Moyasar-Signature": "any_sig"},
        )
        assert any(isinstance(e, PaymentReceived) for e in puow.outbox.events)

    def test_reservation_confirmed_event_enqueued(self) -> None:
        puow = _StubPaymentUow()
        cuow = FakeCheckoutUnitOfWork()
        self._seed_pending_intent(puow)
        client, _, _ = _make_client(payment_uow=puow, checkout_uow=cuow)
        client.post(
            "/api/v1/webhooks/payment",
            content=_paid_webhook_body(),
            headers={"X-Moyasar-Signature": "any_sig"},
        )
        assert any(isinstance(e, ReservationConfirmed) for e in cuow.outbox.events)

    def test_order_created_event_enqueued(self) -> None:
        puow = _StubPaymentUow()
        cuow = FakeCheckoutUnitOfWork()
        self._seed_pending_intent(puow)
        client, _, _ = _make_client(payment_uow=puow, checkout_uow=cuow)
        client.post(
            "/api/v1/webhooks/payment",
            content=_paid_webhook_body(),
            headers={"X-Moyasar-Signature": "any_sig"},
        )
        assert any(isinstance(e, OrderCreated) for e in cuow.outbox.events)

    def test_order_saved_in_repository(self) -> None:
        puow = _StubPaymentUow()
        cuow = FakeCheckoutUnitOfWork()
        self._seed_pending_intent(puow)
        client, _, _ = _make_client(payment_uow=puow, checkout_uow=cuow)
        client.post(
            "/api/v1/webhooks/payment",
            content=_paid_webhook_body(),
            headers={"X-Moyasar-Signature": "any_sig"},
        )
        order = cuow.repository.find_by_reservation_id(_RES_ID)
        assert order is not None

    def test_reservation_status_is_completed(self) -> None:
        puow = _StubPaymentUow()
        cuow = FakeCheckoutUnitOfWork()
        self._seed_pending_intent(puow)
        client, _, _ = _make_client(payment_uow=puow, checkout_uow=cuow)
        client.post(
            "/api/v1/webhooks/payment",
            content=_paid_webhook_body(),
            headers={"X-Moyasar-Signature": "any_sig"},
        )
        rec = cuow.reservation_repository.find_by_id(_RES_ID)
        assert rec is not None and rec.status == "COMPLETED"


# ---------------------------------------------------------------------------
# Gate 3 — Duplicate webhook (idempotent)
# ---------------------------------------------------------------------------

class TestGate3DuplicateWebhook:
    def teardown_method(self) -> None:
        _cleanup()

    def _seed_paid_intent(self, puow: _StubPaymentUow) -> None:
        intent = PaymentIntent(
            id=PaymentIntentId("pi_gate3_test_0001"),
            reservation_id=_RES_ID,
            amount=_AMOUNT,
            currency="SAR",
            status=PaymentStatus.PAID,
            created_at=_NOW,
            expires_at=_VALID_UNTIL,
            provider_reference=_PROVIDER_REF,
            paid_at=_NOW,
        )
        puow.repository.save(intent)

    def test_duplicate_webhook_returns_204(self) -> None:
        puow = _StubPaymentUow()
        self._seed_paid_intent(puow)
        client, _, _ = _make_client(payment_uow=puow)
        r = client.post(
            "/api/v1/webhooks/payment",
            content=_paid_webhook_body(),
            headers={"X-Moyasar-Signature": "any_sig"},
        )
        assert r.status_code == 204

    def test_duplicate_webhook_does_not_enqueue_extra_event(self) -> None:
        puow = _StubPaymentUow()
        self._seed_paid_intent(puow)
        client, _, _ = _make_client(payment_uow=puow)
        client.post(
            "/api/v1/webhooks/payment",
            content=_paid_webhook_body(),
            headers={"X-Moyasar-Signature": "any_sig"},
        )
        assert not any(isinstance(e, PaymentReceived) for e in puow.outbox.events)


# ---------------------------------------------------------------------------
# Gate 4 — Expired intent (paid webhook arrives after expires_at)
# ---------------------------------------------------------------------------

class TestGate4ExpiredIntent:
    def teardown_method(self) -> None:
        _cleanup()

    def _seed_expired_pending(self, puow: _StubPaymentUow) -> None:
        intent = PaymentIntent(
            id=PaymentIntentId("pi_gate4_test_0001"),
            reservation_id=_RES_ID,
            amount=_AMOUNT,
            currency="SAR",
            status=PaymentStatus.PENDING,
            created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2020, 1, 1, 0, 15, tzinfo=timezone.utc),  # clearly past
            provider_reference=_PROVIDER_REF,
        )
        puow.repository.save(intent)

    def test_expired_paid_webhook_returns_204(self) -> None:
        puow = _StubPaymentUow()
        self._seed_expired_pending(puow)
        client, _, _ = _make_client(payment_uow=puow)
        r = client.post(
            "/api/v1/webhooks/payment",
            content=_paid_webhook_body(),
            headers={"X-Moyasar-Signature": "any_sig"},
        )
        assert r.status_code == 204

    def test_expired_paid_webhook_creates_no_order(self) -> None:
        puow = _StubPaymentUow()
        cuow = FakeCheckoutUnitOfWork()
        self._seed_expired_pending(puow)
        client, _, _ = _make_client(payment_uow=puow, checkout_uow=cuow)
        client.post(
            "/api/v1/webhooks/payment",
            content=_paid_webhook_body(),
            headers={"X-Moyasar-Signature": "any_sig"},
        )
        # Expired intent → CheckoutService never called → no Order
        order = cuow.repository.find_by_reservation_id(_RES_ID)
        assert order is None

    def test_expired_paid_webhook_does_not_complete_reservation(self) -> None:
        puow = _StubPaymentUow()
        cuow = FakeCheckoutUnitOfWork()
        self._seed_expired_pending(puow)
        client, _, _ = _make_client(payment_uow=puow, checkout_uow=cuow)
        client.post(
            "/api/v1/webhooks/payment",
            content=_paid_webhook_body(),
            headers={"X-Moyasar-Signature": "any_sig"},
        )
        rec = cuow.reservation_repository.find_by_id(_RES_ID)
        assert rec is None or rec.status == "ACTIVE"


# ---------------------------------------------------------------------------
# Gate 5 — Gateway failure on POST /payments
# ---------------------------------------------------------------------------

class TestGate5GatewayFailure:
    def teardown_method(self) -> None:
        _cleanup()

    def test_gateway_failure_returns_502(self) -> None:
        gw = FakePaymentGateway(fail_on_initiate=True)
        client, _, _ = _make_client(gateway=gw)
        r = client.post("/api/v1/payments", json={"reservation_id": str(_RES_ID)})
        assert r.status_code == 502

    def test_gateway_failure_saves_nothing(self) -> None:
        gw = FakePaymentGateway(fail_on_initiate=True)
        client, puow, _ = _make_client(gateway=gw)
        client.post("/api/v1/payments", json={"reservation_id": str(_RES_ID)})
        assert len(puow.repository.intents) == 0

    def test_gateway_failure_enqueues_no_event(self) -> None:
        gw = FakePaymentGateway(fail_on_initiate=True)
        client, puow, _ = _make_client(gateway=gw)
        client.post("/api/v1/payments", json={"reservation_id": str(_RES_ID)})
        assert len(puow.outbox.events) == 0

    def test_invalid_signature_returns_400(self) -> None:
        puow = _StubPaymentUow()
        intent = PaymentIntent(
            id=PaymentIntentId("pi_sig_test_001"),
            reservation_id=_RES_ID,
            amount=_AMOUNT,
            currency="SAR",
            status=PaymentStatus.PENDING,
            created_at=_NOW,
            expires_at=_VALID_UNTIL,
            provider_reference=_PROVIDER_REF,
        )
        puow.repository.save(intent)

        from yasargold_commerce.infra.moyasar_gateway import MoyasarGateway
        real_gw = MoyasarGateway("pk_test", "real_secret_key")
        app.dependency_overrides[_get_gateway] = lambda: real_gw
        app.dependency_overrides[_get_payment_service] = lambda: PaymentService(real_gw)
        app.dependency_overrides[_get_payment_uow] = lambda: puow
        app.dependency_overrides[_get_checkout_uow] = lambda: FakeCheckoutUnitOfWork()
        app.dependency_overrides[get_db] = lambda: _StubDb()

        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(
            "/api/v1/webhooks/payment",
            content=_paid_webhook_body(),
            headers={"X-Moyasar-Signature": "bad_signature_0000000000000000000000000000000000000"},
        )
        assert r.status_code == 400
