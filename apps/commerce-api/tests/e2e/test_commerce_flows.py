"""E2E integration tests — Gate A production readiness scenarios.

Four scenarios that must pass before production cutover:

  Scenario 1 — Happy path:
    reserve → pay (initiate) → webhook (paid) → order confirmed

  Scenario 2 — Late webhook → refund:
    reserve → item sold at POS (stock→0) → webhook (paid) →
    ADR-013 detects no stock → REFUND_PENDING → RefundWorker → REFUNDED

  Scenario 3 — Duplicate webhook (idempotency):
    payment already PAID → second webhook → 204, no extra events

  Scenario 4 — Refund retry (transient then success):
    REFUND_PENDING intent → RefundWorker tick 1 (transient failure, skipped) →
    RefundWorker tick 2 (success) → REFUNDED

Infrastructure:
    SQLite in-memory (StaticPool) — no PostgreSQL required for local runs.
    All external providers replaced with in-memory fakes.
    JWT auth verified via real auth.py with a test secret.

These tests verify observable state (DB rows, HTTP status codes) not
implementation internals. Each scenario is independent — no shared state.
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from yasargold_commerce.infra.order_orm import OrderRow
from yasargold_commerce.infra.payment_orm import PaymentIntentRow
from yasargold_commerce.infra.reservation_orm import OutboxEventRow, ReservationRow
from yasargold_commerce.models import Item
from yasargold_commerce.workers.refund_worker import RefundWorker
from yasargold_domain.payment.intent import PaymentIntent, PaymentStatus
from yasargold_domain.orders.events import OrderCreated
from yasargold_domain.payment.events import RefundConfirmed
from yasargold_domain.payment.testing import FakePaymentGateway, FakeRefundGateway

# Fully-qualified event type strings as stored in outbox_events.event_type
_ORDER_CREATED_ET = f"{OrderCreated.__module__}.{OrderCreated.__qualname__}"
_REFUND_CONFIRMED_ET = f"{RefundConfirmed.__module__}.{RefundConfirmed.__qualname__}"
from yasargold_domain.shared.identifiers import (
    PaymentIntentId,
    ReservationId,
)

from .conftest import E2E_CUSTOMER_REF, E2E_ITEM_CODE, E2E_ITEM_PRICE, make_customer_token

_NOW = datetime.now(timezone.utc)
_VALID_UNTIL = _NOW + timedelta(minutes=15)


# ===========================================================================
# Scenario 1 — Happy path: reserve → pay → webhook → order confirmed
# ===========================================================================

class TestHappyPath:
    """End-to-end flow for a successful gold purchase."""

    def test_reserve_returns_201(self, client, seed_db):
        r = client.post(
            "/api/v1/reservations",
            json={"item_slug": E2E_ITEM_CODE.lower()},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert "reservation_id" in body
        assert body["item_slug"] == E2E_ITEM_CODE.lower()

    def test_payment_initiate_returns_201(self, client, seed_db):
        r = client.post(
            "/api/v1/reservations",
            json={"item_slug": E2E_ITEM_CODE.lower()},
        )
        reservation_id = r.json()["reservation_id"]

        r2 = client.post("/api/v1/payments", json={"reservation_id": reservation_id})
        assert r2.status_code == 201, r2.text
        body = r2.json()
        assert "payment_intent_id" in body
        assert "checkout_url" in body

    def test_webhook_creates_order(self, client, seed_db, SessionLocal):
        # Step 1: reserve
        r1 = client.post(
            "/api/v1/reservations",
            json={"item_slug": E2E_ITEM_CODE.lower()},
        )
        reservation_id = r1.json()["reservation_id"]

        # Step 2: initiate payment
        r2 = client.post("/api/v1/payments", json={"reservation_id": reservation_id})
        assert r2.status_code == 201

        # Step 3: paid webhook (FakePaymentGateway skips signature check)
        r3 = client.post(
            "/api/v1/webhooks/payment",
            content=b'{"type":"paid"}',
            headers={"X-Moyasar-Signature": "fake-sig"},
        )
        assert r3.status_code == 204, r3.text

        # Assert: order row exists
        db = SessionLocal()
        try:
            order = db.execute(
                select(OrderRow).where(OrderRow.reservation_id == reservation_id)
            ).scalar_one_or_none()
            assert order is not None, "Order must be created after paid webhook"
            assert order.status == "CONFIRMED"
        finally:
            db.close()

    def test_webhook_completes_reservation(self, client, seed_db, SessionLocal):
        r1 = client.post(
            "/api/v1/reservations",
            json={"item_slug": E2E_ITEM_CODE.lower()},
        )
        reservation_id = r1.json()["reservation_id"]
        client.post("/api/v1/payments", json={"reservation_id": reservation_id})
        client.post(
            "/api/v1/webhooks/payment",
            content=b'{"type":"paid"}',
            headers={"X-Moyasar-Signature": "fake-sig"},
        )

        db = SessionLocal()
        try:
            row = db.execute(
                select(ReservationRow).where(ReservationRow.id == reservation_id)
            ).scalar_one_or_none()
            assert row is not None
            assert row.status == "COMPLETED"
        finally:
            db.close()

    def test_webhook_enqueues_order_created_event(self, client, seed_db, SessionLocal):
        r1 = client.post(
            "/api/v1/reservations",
            json={"item_slug": E2E_ITEM_CODE.lower()},
        )
        reservation_id = r1.json()["reservation_id"]
        client.post("/api/v1/payments", json={"reservation_id": reservation_id})
        client.post(
            "/api/v1/webhooks/payment",
            content=b'{"type":"paid"}',
            headers={"X-Moyasar-Signature": "fake-sig"},
        )

        db = SessionLocal()
        try:
            events = db.execute(
                select(OutboxEventRow).where(OutboxEventRow.event_type == _ORDER_CREATED_ET)
            ).scalars().all()
            assert len(events) == 1, "Exactly one OrderCreated event must be enqueued"
        finally:
            db.close()

    def test_get_order_returns_200(self, client, seed_db, SessionLocal):
        """GET /orders/{order_id} returns the order after successful checkout."""
        r1 = client.post(
            "/api/v1/reservations",
            json={"item_slug": E2E_ITEM_CODE.lower()},
        )
        reservation_id = r1.json()["reservation_id"]
        client.post("/api/v1/payments", json={"reservation_id": reservation_id})
        client.post(
            "/api/v1/webhooks/payment",
            content=b'{"type":"paid"}',
            headers={"X-Moyasar-Signature": "fake-sig"},
        )

        db = SessionLocal()
        try:
            order_row = db.execute(
                select(OrderRow).where(OrderRow.reservation_id == reservation_id)
            ).scalar_one()
            order_id = order_row.id
        finally:
            db.close()

        r = client.get(f"/api/v1/orders/{order_id}")
        assert r.status_code == 200, r.text
        assert r.json()["reservation_id"] == reservation_id


# ===========================================================================
# Scenario 2 — Late webhook → REFUND_PENDING → RefundWorker → REFUNDED
# ===========================================================================

class TestLateWebhookRefund:
    """Item sold at POS after reservation; payment arrives → ADR-013 triggers refund."""

    def _setup_flow(self, client, seed_db, SessionLocal):
        """Reserve, initiate payment, then zero out item stock to simulate POS sale."""
        r1 = client.post(
            "/api/v1/reservations",
            json={"item_slug": E2E_ITEM_CODE.lower()},
        )
        reservation_id = r1.json()["reservation_id"]

        client.post("/api/v1/payments", json={"reservation_id": reservation_id})

        # Simulate POS sale: item stock drops to 0 while payment was in flight
        db = SessionLocal()
        try:
            db.execute(
                Item.__table__.update()
                .where(Item.item_code == E2E_ITEM_CODE)
                .values(stock=0)
            )
            db.commit()
        finally:
            db.close()

        return reservation_id

    def test_webhook_creates_refund_pending_when_stock_zero(
        self, client, seed_db, SessionLocal
    ):
        """ADR-013: paid webhook with stock=0 → REFUND_PENDING (not PAID + Order)."""
        self._setup_flow(client, seed_db, SessionLocal)

        r = client.post(
            "/api/v1/webhooks/payment",
            content=b'{"type":"paid"}',
            headers={"X-Moyasar-Signature": "fake-sig"},
        )
        assert r.status_code == 204

        db = SessionLocal()
        try:
            intent_row = db.execute(
                select(PaymentIntentRow).where(
                    PaymentIntentRow.status == PaymentStatus.REFUND_PENDING.value
                )
            ).scalar_one_or_none()
            assert intent_row is not None, "Intent must be REFUND_PENDING when stock=0"
        finally:
            db.close()

    def test_no_order_created_when_stock_zero(self, client, seed_db, SessionLocal):
        """No Order row must exist when ADR-013 diverts to REFUND_PENDING."""
        reservation_id = self._setup_flow(client, seed_db, SessionLocal)
        client.post(
            "/api/v1/webhooks/payment",
            content=b'{"type":"paid"}',
            headers={"X-Moyasar-Signature": "fake-sig"},
        )

        db = SessionLocal()
        try:
            order = db.execute(
                select(OrderRow).where(OrderRow.reservation_id == reservation_id)
            ).scalar_one_or_none()
            assert order is None, "No Order must be created when stock=0 (refund path)"
        finally:
            db.close()

    def test_refund_worker_processes_pending_intent(self, client, seed_db, SessionLocal):
        """RefundWorker.run_once() transitions REFUND_PENDING → REFUNDED."""
        self._setup_flow(client, seed_db, SessionLocal)
        client.post(
            "/api/v1/webhooks/payment",
            content=b'{"type":"paid"}',
            headers={"X-Moyasar-Signature": "fake-sig"},
        )

        fake_gw = FakeRefundGateway()
        worker = RefundWorker(session_factory=SessionLocal, gateway=fake_gw)
        refunded = worker.run_once()

        assert refunded == 1
        assert fake_gw.refund_count == 1

        db = SessionLocal()
        try:
            intent_row = db.execute(
                select(PaymentIntentRow).where(
                    PaymentIntentRow.status == PaymentStatus.REFUNDED.value
                )
            ).scalar_one_or_none()
            assert intent_row is not None, "Intent must be REFUNDED after worker run"
        finally:
            db.close()

    def test_refund_worker_enqueues_refund_confirmed_event(
        self, client, seed_db, SessionLocal
    ):
        """RefundWorker enqueues a RefundConfirmed outbox event on success."""
        self._setup_flow(client, seed_db, SessionLocal)
        client.post(
            "/api/v1/webhooks/payment",
            content=b'{"type":"paid"}',
            headers={"X-Moyasar-Signature": "fake-sig"},
        )

        worker = RefundWorker(session_factory=SessionLocal, gateway=FakeRefundGateway())
        worker.run_once()

        db = SessionLocal()
        try:
            events = db.execute(
                select(OutboxEventRow).where(OutboxEventRow.event_type == _REFUND_CONFIRMED_ET)
            ).scalars().all()
            assert len(events) == 1
        finally:
            db.close()


# ===========================================================================
# Scenario 3 — Duplicate webhook (idempotency)
# ===========================================================================

class TestDuplicateWebhook:
    """Second webhook for an already-PAID intent is silently accepted (204)."""

    def test_duplicate_webhook_returns_204(self, client, seed_db, SessionLocal):
        # Full flow once
        r1 = client.post(
            "/api/v1/reservations",
            json={"item_slug": E2E_ITEM_CODE.lower()},
        )
        reservation_id = r1.json()["reservation_id"]
        client.post("/api/v1/payments", json={"reservation_id": reservation_id})
        client.post(
            "/api/v1/webhooks/payment",
            content=b'{"type":"paid"}',
            headers={"X-Moyasar-Signature": "fake-sig"},
        )

        # Second webhook (duplicate)
        r2 = client.post(
            "/api/v1/webhooks/payment",
            content=b'{"type":"paid"}',
            headers={"X-Moyasar-Signature": "fake-sig"},
        )
        assert r2.status_code == 204

    def test_duplicate_webhook_creates_no_extra_order(self, client, seed_db, SessionLocal):
        r1 = client.post(
            "/api/v1/reservations",
            json={"item_slug": E2E_ITEM_CODE.lower()},
        )
        reservation_id = r1.json()["reservation_id"]
        client.post("/api/v1/payments", json={"reservation_id": reservation_id})
        # First webhook
        client.post(
            "/api/v1/webhooks/payment",
            content=b'{"type":"paid"}',
            headers={"X-Moyasar-Signature": "fake-sig"},
        )
        # Duplicate webhook
        client.post(
            "/api/v1/webhooks/payment",
            content=b'{"type":"paid"}',
            headers={"X-Moyasar-Signature": "fake-sig"},
        )

        db = SessionLocal()
        try:
            orders = db.execute(
                select(OrderRow).where(OrderRow.reservation_id == reservation_id)
            ).scalars().all()
            assert len(orders) == 1, "Duplicate webhook must not create a second Order"
        finally:
            db.close()

    def test_duplicate_webhook_creates_no_extra_event(self, client, seed_db, SessionLocal):
        r1 = client.post(
            "/api/v1/reservations",
            json={"item_slug": E2E_ITEM_CODE.lower()},
        )
        reservation_id = r1.json()["reservation_id"]
        client.post("/api/v1/payments", json={"reservation_id": reservation_id})
        client.post(
            "/api/v1/webhooks/payment",
            content=b'{"type":"paid"}',
            headers={"X-Moyasar-Signature": "fake-sig"},
        )
        client.post(
            "/api/v1/webhooks/payment",
            content=b'{"type":"paid"}',
            headers={"X-Moyasar-Signature": "fake-sig"},
        )

        db = SessionLocal()
        try:
            events = db.execute(
                select(OutboxEventRow).where(OutboxEventRow.event_type == _ORDER_CREATED_ET)
            ).scalars().all()
            assert len(events) == 1, "Duplicate webhook must not enqueue second OrderCreated"
        finally:
            db.close()


# ===========================================================================
# Scenario 4 — Refund retry: transient failure on tick 1, success on tick 2
# ===========================================================================

class TestRefundRetry:
    """RefundWorker skips REFUND_PENDING on transient failure; succeeds on next tick."""

    def _seed_refund_pending(self, SessionLocal) -> str:
        """Directly insert a REFUND_PENDING intent, bypassing the HTTP layer."""
        from yasargold_domain.shared.identifiers import ReservationId as RId
        intent_id = "pi_e2e_refund_retry_001"
        reservation_id = "res_e2e_refund_retry_001"

        db = SessionLocal()
        try:
            # Seed a minimal reservation row so FK constraints pass (if any)
            res_row = ReservationRow(
                id=reservation_id,
                quote_id="q_e2e_001",
                item_id=1,
                gold_price_id=1,
                locked_rate_per_gram_24k="250.000000",
                karat_rate_per_gram="250.000000",
                pricing_engine_version="1.0",
                reserved_at=_NOW,
                valid_until=_VALID_UNTIL,
                status="ACTIVE",
                customer_phone=E2E_CUSTOMER_REF,
            )
            db.add(res_row)

            intent_row = PaymentIntentRow(
                id=intent_id,
                reservation_id=reservation_id,
                amount="5500.00",
                currency="SAR",
                status=PaymentStatus.REFUND_PENDING.value,
                created_at=_NOW,
                expires_at=_VALID_UNTIL,
                provider_reference="pay_e2e_retry_001",
            )
            db.add(intent_row)
            db.commit()
        finally:
            db.close()
        return intent_id

    def test_transient_failure_leaves_intent_refund_pending(self, engine, seed_db, SessionLocal):
        """Tick 1: transient error → intent stays REFUND_PENDING, run_once returns 0."""
        self._seed_refund_pending(SessionLocal)

        gw = FakeRefundGateway(fail_transient_on_next=True)
        worker = RefundWorker(session_factory=SessionLocal, gateway=gw)
        result = worker.run_once()

        assert result == 0

        db = SessionLocal()
        try:
            row = db.execute(
                select(PaymentIntentRow).where(
                    PaymentIntentRow.status == PaymentStatus.REFUND_PENDING.value
                )
            ).scalar_one_or_none()
            assert row is not None, "Intent must remain REFUND_PENDING after transient failure"
        finally:
            db.close()

    def test_success_after_transient_failure(self, engine, seed_db, SessionLocal):
        """Tick 1: transient → skipped. Tick 2: success → REFUNDED."""
        self._seed_refund_pending(SessionLocal)

        gw = FakeRefundGateway(fail_transient_on_next=True)
        worker = RefundWorker(session_factory=SessionLocal, gateway=gw)

        tick1 = worker.run_once()  # transient failure, gateway flag self-clears
        tick2 = worker.run_once()  # now succeeds

        assert tick1 == 0
        assert tick2 == 1
        assert gw.refund_count == 1

        db = SessionLocal()
        try:
            row = db.execute(
                select(PaymentIntentRow).where(
                    PaymentIntentRow.status == PaymentStatus.REFUNDED.value
                )
            ).scalar_one_or_none()
            assert row is not None, "Intent must be REFUNDED after second tick"
        finally:
            db.close()

    def test_permanent_failure_leaves_intent_for_manual_review(
        self, engine, seed_db, SessionLocal
    ):
        """Permanent failure → intent stays REFUND_PENDING (manual intervention)."""
        self._seed_refund_pending(SessionLocal)

        gw = FakeRefundGateway(fail_permanent_on_next=True)
        worker = RefundWorker(session_factory=SessionLocal, gateway=gw)
        result = worker.run_once()

        assert result == 0

        db = SessionLocal()
        try:
            row = db.execute(
                select(PaymentIntentRow).where(
                    PaymentIntentRow.status == PaymentStatus.REFUND_PENDING.value
                )
            ).scalar_one_or_none()
            assert row is not None, "Intent must stay REFUND_PENDING for manual review"
        finally:
            db.close()
