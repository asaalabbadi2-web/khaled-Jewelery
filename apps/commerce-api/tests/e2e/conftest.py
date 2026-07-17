"""Shared fixtures for E2E integration tests.

Database strategy:
    SQLite in-memory with StaticPool — all sessions share one connection, so
    data seeded before an HTTP call is visible inside the request handler.
    A new engine is created per test to ensure full isolation.

    Production uses PostgreSQL (SELECT FOR UPDATE NOWAIT, partial indexes).
    SQLite silently ignores WITH FOR UPDATE; the locking logic is tested by
    the PostgreSQL-targeted staging run, not here. What these tests verify
    is the end-to-end flow: HTTP → domain → repository → DB state.

Auth strategy:
    JWT tokens are generated with a test secret. The JWT_SECRET_KEY env var
    is set via monkeypatch so auth.py picks it up without patching internals.

Gateway strategy:
    FakePaymentGateway replaces MoyasarGateway for all E2E tests.
    FakeRefundGateway is passed directly to RefundWorker (no HTTP layer).
    No network calls are made in any E2E test.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import jwt as _jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Import ALL ORM modules before Base.metadata.create_all — each import
# registers the model's __tablename__ with the shared Base metadata.
import yasargold_commerce.infra.notification_orm  # noqa: F401
import yasargold_commerce.infra.order_orm  # noqa: F401
import yasargold_commerce.infra.payment_orm  # noqa: F401
import yasargold_commerce.infra.reconciliation_orm  # noqa: F401
import yasargold_commerce.infra.reservation_orm  # noqa: F401
import yasargold_commerce.infra.shipment_orm  # noqa: F401
import yasargold_commerce.models  # noqa: F401  — category, item, gold_price

from yasargold_commerce.auth import get_customer_ref
from yasargold_commerce.db import Base, get_db
from yasargold_commerce.main import app
from yasargold_commerce.models import GoldPrice, Item
from yasargold_commerce.routers.payments import (
    _get_checkout_uow,
    _get_gateway,
    _get_payment_service,
    _get_payment_uow,
)
from yasargold_domain.payment.testing import FakePaymentGateway
from yasargold_domain.payment.service import PaymentService

# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------

E2E_JWT_SECRET = "e2e-test-secret-not-for-production-use"
E2E_CUSTOMER_REF = "+966500000001"
E2E_ITEM_CODE = "RING24K001"
E2E_ITEM_PRICE = Decimal("5500.00")
E2E_ITEM_KARAT = "24"

# ERP stores gold_price.date as naive Riyadh local time (UTC+3).
# The router treats naive datetimes as Riyadh when computing quote age.
# We must store the price date as Riyadh local time to avoid a false 3-hour age.
_NOW = datetime.now(timezone.utc)
_RIYADH = timezone(timedelta(hours=3))
E2E_GOLD_PRICE = 250.0  # SAR per gram (spot)
# 30s ago in Riyadh local time, stored naive (as ERP does)
E2E_GOLD_PRICE_DATE = (datetime.now(_RIYADH) - timedelta(seconds=30)).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine():
    """Fresh SQLite in-memory DB per test. StaticPool = all sessions share one connection."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def SessionLocal(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


@pytest.fixture
def seed_db(engine, SessionLocal):
    """Seed minimal ERP read-only tables (Item + GoldPrice) into the test DB."""
    session = SessionLocal()
    try:
        item = Item(
            id=1,
            item_code=E2E_ITEM_CODE,
            name="Gold Ring 24K",
            karat=E2E_ITEM_KARAT,
            price=float(E2E_ITEM_PRICE),
            stock=1,
        )
        gp = GoldPrice(
            id=1,
            price=E2E_GOLD_PRICE,
            date=E2E_GOLD_PRICE_DATE,  # already naive Riyadh local time
        )
        session.add(item)
        session.add(gp)
        session.commit()
    finally:
        session.close()
    return {"item_id": 1, "item_code": E2E_ITEM_CODE}


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    """Set required env vars for JWT and commerce API."""
    monkeypatch.setenv("JWT_SECRET_KEY", E2E_JWT_SECRET)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")  # satisfies import checks




@pytest.fixture
def gateway():
    return FakePaymentGateway()


@pytest.fixture
def client(engine, SessionLocal, gateway):
    """TestClient wired to the test DB and FakePaymentGateway."""
    def _get_db_override():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[_get_gateway] = lambda: gateway
    app.dependency_overrides[_get_payment_service] = lambda: PaymentService(gateway)
    app.dependency_overrides[get_customer_ref] = lambda: E2E_CUSTOMER_REF

    yield TestClient(app, raise_server_exceptions=False)

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def make_customer_token(sub: str = E2E_CUSTOMER_REF) -> str:
    return _jwt.encode(
        {
            "sub": sub,
            "scope": "customer",
            "exp": int((_NOW + timedelta(hours=1)).timestamp()),
            "iat": int(_NOW.timestamp()),
        },
        E2E_JWT_SECRET,
        algorithm="HS256",
    )


def make_admin_token() -> str:
    return _jwt.encode(
        {
            "sub": "admin",
            "scope": "admin",
            "exp": int((_NOW + timedelta(hours=1)).timestamp()),
            "iat": int(_NOW.timestamp()),
        },
        E2E_JWT_SECRET,
        algorithm="HS256",
    )
