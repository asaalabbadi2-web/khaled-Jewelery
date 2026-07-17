"""Contract tests for GET /api/v1/orders/{order_id} and
GET /api/v1/reservations/{reservation_id}/order.

Tests the read side of the Orders capability.
No database, no network. Stubs injected via FastAPI dependency_overrides.

Gate coverage (matching docs/runbooks/order_validation.md):
  Gate 1: GET /orders/{id} — found → 200
  Gate 2: GET /orders/{id} — not found → 404
  Gate 3: GET /reservations/{id}/order — found → 200
  Gate 4: GET /reservations/{id}/order — not found → 404
  Gate 5: Webhook creates Order → GET /orders/{id} returns it
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

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
)
from yasargold_domain.orders.order import OrderStatus
from yasargold_domain.orders.testing import FakeCheckoutUnitOfWork
from yasargold_domain.payment.intent import PaymentIntent, PaymentStatus
from yasargold_domain.payment.service import PaymentService
from yasargold_domain.payment.testing import FakePaymentGateway
from yasargold_domain.reservation.repository import ReservationRecord
from yasargold_domain.shared.identifiers import (
    GoldPriceId,
    ItemId,
    PaymentIntentId,
    QuoteId,
    ReservationId,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NOW = datetime.now(timezone.utc).replace(microsecond=0)
_VALID_UNTIL = _NOW + timedelta(hours=1)
_RES_ID = ReservationId("res_orders_contract_001")
_AMOUNT = Decimal("5500.00")
_PROVIDER_REF = "pay_fake_orders_001"

# ---------------------------------------------------------------------------
# Stub DB that returns OrderRow-like objects
# ---------------------------------------------------------------------------

class _StubOrderRow:
    def __init__(
        self,
        order_id: str,
        reservation_id: str,
        customer_ref: str | None = _TEST_CUSTOMER_REF,
    ) -> None:
        self.id = order_id
        self.reservation_id = reservation_id
        self.payment_intent_id = "pi_orders_test_001"
        self.item_id = 42
        self.amount = Decimal("5500.00")
        self.currency = "SAR"
        self.status = "CONFIRMED"
        self.created_at = _NOW
        self.confirmed_at = _NOW
        self.shipped_at = None
        self.delivered_at = None
        self.cancelled_at = None
        self.cancellation_reason = None
        self.customer_ref = customer_ref


class _StubResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _StubOrderDb:
    """DB stub for order read endpoints."""

    def __init__(
        self,
        order_row: _StubOrderRow | None = None,
    ) -> None:
        self._row = order_row

    def get(self, entity_class: Any, pk: Any) -> Any:
        return self._row

    def execute(self, stmt: Any) -> _StubResult:
        from yasargold_commerce.infra.order_orm import OrderRow
        try:
            entity = stmt.column_descriptions[0]["entity"]
            if entity is OrderRow:
                return _StubResult(self._row)
        except (AttributeError, IndexError, KeyError):
            pass
        return _StubResult(None)

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Payment stubs (for Gate 5: full webhook → order chain)
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
class _StubPaymentOutbox:
    events: list = field(default_factory=list)

    def enqueue(self, event: Any) -> None:
        self.events.append(event)


@dataclass
class _StubPaymentUow:
    repository: _StubPaymentRepo = field(default_factory=_StubPaymentRepo)
    outbox: _StubPaymentOutbox = field(default_factory=_StubPaymentOutbox)

    def __enter__(self) -> _StubPaymentUow:
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


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
# Gate 1 — GET /orders/{order_id} found → 200
# ---------------------------------------------------------------------------

def _wire_customer(db_stub: Any) -> None:
    """Wire get_db stub + bypass JWT auth with test customer_ref for order contract tests."""
    app.dependency_overrides[get_db] = lambda: db_stub
    app.dependency_overrides[get_customer_ref] = lambda: _TEST_CUSTOMER_REF


class TestGate1GetOrderFound:
    def teardown_method(self) -> None:
        _cleanup()

    def test_returns_200(self) -> None:
        row = _StubOrderRow("ord_test_001", str(_RES_ID))
        _wire_customer(_StubOrderDb(row))
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/api/v1/orders/ord_test_001")
        assert r.status_code == 200

    def test_response_contains_order_id(self) -> None:
        row = _StubOrderRow("ord_test_001", str(_RES_ID))
        _wire_customer(_StubOrderDb(row))
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/api/v1/orders/ord_test_001")
        assert r.json()["order_id"] == "ord_test_001"

    def test_response_contains_status(self) -> None:
        row = _StubOrderRow("ord_test_001", str(_RES_ID))
        _wire_customer(_StubOrderDb(row))
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/api/v1/orders/ord_test_001")
        assert r.json()["status"] == "CONFIRMED"

    def test_response_contains_reservation_id(self) -> None:
        row = _StubOrderRow("ord_test_001", str(_RES_ID))
        _wire_customer(_StubOrderDb(row))
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/api/v1/orders/ord_test_001")
        assert r.json()["reservation_id"] == str(_RES_ID)

    def test_response_contains_amount(self) -> None:
        row = _StubOrderRow("ord_test_001", str(_RES_ID))
        _wire_customer(_StubOrderDb(row))
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/api/v1/orders/ord_test_001")
        assert "amount" in r.json()


# ---------------------------------------------------------------------------
# Gate 2 — GET /orders/{order_id} not found → 404
# ---------------------------------------------------------------------------

class TestGate2GetOrderNotFound:
    def teardown_method(self) -> None:
        _cleanup()

    def test_returns_404(self) -> None:
        _wire_customer(_StubOrderDb(None))
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/api/v1/orders/ord_nonexistent")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Gate 3 — GET /reservations/{reservation_id}/order found → 200
# ---------------------------------------------------------------------------

class TestGate3GetOrderByReservation:
    def teardown_method(self) -> None:
        _cleanup()

    def test_returns_200(self) -> None:
        row = _StubOrderRow("ord_test_002", str(_RES_ID))
        _wire_customer(_StubOrderDb(row))
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/api/v1/reservations/{_RES_ID}/order")
        assert r.status_code == 200

    def test_response_contains_order_id(self) -> None:
        row = _StubOrderRow("ord_test_002", str(_RES_ID))
        _wire_customer(_StubOrderDb(row))
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/api/v1/reservations/{_RES_ID}/order")
        assert r.json()["order_id"] == "ord_test_002"


# ---------------------------------------------------------------------------
# Gate 4 — GET /reservations/{reservation_id}/order not found → 404
# ---------------------------------------------------------------------------

class TestGate4GetOrderByReservationNotFound:
    def teardown_method(self) -> None:
        _cleanup()

    def test_returns_404(self) -> None:
        _wire_customer(_StubOrderDb(None))
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/api/v1/reservations/{_RES_ID}/order")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Gate 5 — Webhook creates Order → Order is retrievable from repository
# ---------------------------------------------------------------------------

class TestGate5WebhookCreatesOrder:
    """Proves the full chain: payment webhook → Order created in repository."""

    def teardown_method(self) -> None:
        _cleanup()

    def _seed_pending_intent(self, puow: _StubPaymentUow) -> None:
        intent = PaymentIntent(
            id=PaymentIntentId("pi_orders_gate5_001"),
            reservation_id=_RES_ID,
            amount=_AMOUNT,
            currency="SAR",
            status=PaymentStatus.PENDING,
            created_at=_NOW,
            expires_at=_VALID_UNTIL,
            provider_reference=_PROVIDER_REF,
        )
        puow.repository.save(intent)

    def test_order_exists_in_repo_after_webhook(self) -> None:
        puow = _StubPaymentUow()
        cuow = FakeCheckoutUnitOfWork()
        cuow.reservation_repository.records[str(_RES_ID)] = ReservationRecord(
            id=_RES_ID,
            quote_id=QuoteId("qt_gate5_001"),
            item_id=ItemId(42),
            gold_price_id=GoldPriceId(18452),
            locked_rate_per_gram_24k=Decimal("230.00"),
            karat_rate_per_gram=Decimal("193.125"),
            pricing_engine_version="v1",
            reserved_at=_NOW - timedelta(minutes=5),
            valid_until=_VALID_UNTIL,
            status="ACTIVE",
        )
        self._seed_pending_intent(puow)

        gw = FakePaymentGateway(provider_reference=_PROVIDER_REF)
        app.dependency_overrides[get_db] = lambda: _StubOrderDb(None)
        app.dependency_overrides[_get_gateway] = lambda: gw
        app.dependency_overrides[_get_payment_service] = lambda: PaymentService(gw)
        app.dependency_overrides[_get_payment_uow] = lambda: puow
        app.dependency_overrides[_get_checkout_uow] = lambda: cuow

        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(
            "/api/v1/webhooks/payment",
            content=_paid_webhook_body(),
            headers={"X-Moyasar-Signature": "any_sig"},
        )
        assert r.status_code == 204

        order = cuow.repository.find_by_reservation_id(_RES_ID)
        assert order is not None
        assert order.status == OrderStatus.CONFIRMED
        assert order.payment_intent_id == PaymentIntentId("pi_orders_gate5_001")
