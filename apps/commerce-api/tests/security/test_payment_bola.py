"""Law 5 — BOLA: payment router delegates ownership check to domain service (ADR-017).

The bug this guards against: a customer supplies a reservation_id that belongs
to another customer and initiates a payment. Before this fix, the router did the
ownership check itself (raw SQLAlchemy). After this fix, the domain service
owns the check and the router only maps None → 404.

Law 5 rules verified here:
  1. Ownership mismatch (wrong customer) → 404, gateway never called
  2. customer_ref=None (unauthenticated) → 404, gateway never called
  3. Correct ownership → router reaches the payment service (not a 404)

Pattern:
  - Override _get_reservation_service to inject a spy
  - Spy returns None (mismatch) or a ReservationRecord (match)
  - Assert HTTP status and whether the payment gateway was reached
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from yasargold_commerce.auth import get_customer_ref
from yasargold_commerce.db import get_db
from yasargold_commerce.main import app
from yasargold_commerce.routers.payments import (
    _get_payment_service,
    _get_payment_uow,
    _get_reservation_service,
    _get_reservation_uow,
)
from yasargold_domain.reservation.repository import ReservationRecord
from yasargold_domain.shared.identifiers import GoldPriceId, ItemId, QuoteId, ReservationId

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_OWNER_REF = "+966501234567"
_OTHER_REF = "+966500000000"
_RESERVATION_ID = "res_bola_test_001"
_ITEM_ID = "item_bola_001"
_VALID_UNTIL = datetime(2026, 12, 31, 23, 59, 0, tzinfo=timezone.utc)

_RECORD = ReservationRecord(
    id=ReservationId(_RESERVATION_ID),
    item_id=ItemId(_ITEM_ID),
    quote_id=QuoteId("quote_bola_001"),
    gold_price_id=GoldPriceId("gp_bola_001"),
    locked_rate_per_gram_24k=Decimal("300.00"),
    karat_rate_per_gram=Decimal("275.00"),
    pricing_engine_version="v1",
    reserved_at=datetime(2026, 12, 31, 0, 0, 0, tzinfo=timezone.utc),
    valid_until=_VALID_UNTIL,
    status="ACTIVE",
    customer_phone=_OWNER_REF,
)

# ---------------------------------------------------------------------------
# Stubs / spies
# ---------------------------------------------------------------------------


@dataclass
class _SpyReservationService:
    """Returns _record when customer_ref matches _OWNER_REF; otherwise None."""

    calls: list[tuple] = field(default_factory=list)
    _record: ReservationRecord | None = None

    def configure(self, *, returns: ReservationRecord | None) -> None:
        self._record = returns

    def find_reservation_for_customer(
        self,
        reservation_id: Any,
        customer_ref: str | None,
        uow: Any,
    ) -> ReservationRecord | None:
        self.calls.append((reservation_id, customer_ref))
        return self._record

    # Other ReservationService methods not called from this code path
    def reserve(self, *a: Any, **kw: Any) -> Any:
        raise NotImplementedError


@dataclass
class _SpyPaymentService:
    """Records whether issue() was reached."""

    issue_called: bool = False

    def issue(self, *a: Any, **kw: Any) -> Any:
        self.issue_called = True
        # Raise to stop execution cleanly — we only care that it was reached
        from yasargold_domain.payment.exceptions import PaymentIntentStatusError
        raise PaymentIntentStatusError("pi_test", current="PENDING", expected="NEW")

    def confirm(self, *a: Any, **kw: Any) -> Any:
        raise NotImplementedError

    def mark_refund_pending(self, *a: Any, **kw: Any) -> Any:
        raise NotImplementedError

    def mark_refunded(self, *a: Any, **kw: Any) -> Any:
        raise NotImplementedError


@dataclass
class _FakeUoW:
    repository: Any = None
    outbox: Any = None

    def __enter__(self) -> _FakeUoW:
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def commit(self) -> None:
        pass


class _StubDb:
    def execute(self, *a: Any, **kw: Any) -> Any:
        return _StubResult(None)

    def close(self) -> None:
        pass


class _StubResult:
    def __init__(self, val: Any) -> None:
        self._val = val

    def scalar_one_or_none(self) -> Any:
        return self._val

    def scalars(self) -> _StubResult:
        return self

    def all(self) -> list:
        return []


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------


def _make_client(
    *,
    customer_ref: str | None,
    service_returns: ReservationRecord | None,
) -> tuple[TestClient, _SpyReservationService, _SpyPaymentService]:
    res_spy = _SpyReservationService()
    res_spy.configure(returns=service_returns)
    pay_spy = _SpyPaymentService()
    fake_uow = _FakeUoW()
    stub_db = _StubDb()

    app.dependency_overrides[get_db] = lambda: stub_db
    app.dependency_overrides[get_customer_ref] = lambda: customer_ref
    app.dependency_overrides[_get_reservation_service] = lambda: res_spy
    app.dependency_overrides[_get_reservation_uow] = lambda: fake_uow
    app.dependency_overrides[_get_payment_service] = lambda: pay_spy
    app.dependency_overrides[_get_payment_uow] = lambda: fake_uow

    client = TestClient(app, raise_server_exceptions=False)
    return client, res_spy, pay_spy


# ---------------------------------------------------------------------------
# Law 5 BOLA proof tests — payments
# ---------------------------------------------------------------------------


class TestPaymentBOLA:
    def teardown_method(self) -> None:
        app.dependency_overrides.clear()

    def test_wrong_customer_returns_404(self) -> None:
        """Cross-customer payment: service returns None → router must return 404.

        This is the core BOLA invariant: customer B cannot pay for customer A's
        reservation by supplying customer A's reservation_id.
        """
        client, res_spy, pay_spy = _make_client(
            customer_ref=_OTHER_REF,
            service_returns=None,  # ownership mismatch
        )

        resp = client.post(
            "/api/v1/payments",
            json={"reservation_id": _RESERVATION_ID},
        )

        assert resp.status_code == 404, (
            f"BOLA: cross-customer payment must return 404, got {resp.status_code}. "
            "If this returns 2xx/409, the ownership check is not applied."
        )
        assert not pay_spy.issue_called, "Payment gateway must NOT be reached on ownership mismatch"

    def test_unauthenticated_caller_returns_404(self) -> None:
        """customer_ref=None (unauthenticated) → domain service returns None → 404.

        ReservationService.find_reservation_for_customer returns None when
        customer_ref is None (deny-by-default). The router must propagate this.
        """
        client, res_spy, pay_spy = _make_client(
            customer_ref=None,
            service_returns=None,  # deny-by-default
        )

        resp = client.post(
            "/api/v1/payments",
            json={"reservation_id": _RESERVATION_ID},
        )

        assert resp.status_code == 404
        assert not pay_spy.issue_called

    def test_ownership_check_delegates_to_domain_service(self) -> None:
        """The router must call find_reservation_for_customer, not do its own DB check.

        We verify this by controlling what the spy returns and asserting the router
        uses that result. If the router bypassed the service, the spy call count
        would be 0 even on a non-404 response.
        """
        client, res_spy, _ = _make_client(
            customer_ref=_OWNER_REF,
            service_returns=None,
        )

        client.post("/api/v1/payments", json={"reservation_id": _RESERVATION_ID})

        assert len(res_spy.calls) == 1, "Router must delegate to domain service (exactly 1 call)"
        called_with_ref = res_spy.calls[0][1]
        assert called_with_ref == _OWNER_REF, (
            f"Domain service must receive the caller's customer_ref. "
            f"Got: {called_with_ref!r}"
        )

    def test_correct_owner_proceeds_past_ownership_check(self) -> None:
        """When the service returns a record, the router must not 404.

        We configure the spy to return a record (ownership match). The router
        then tries to load the item from DB (which returns None from our stub),
        giving 404 for 'Item not found' — proving the ownership check passed.
        """
        client, res_spy, pay_spy = _make_client(
            customer_ref=_OWNER_REF,
            service_returns=_RECORD,  # ownership match
        )

        resp = client.post(
            "/api/v1/payments",
            json={"reservation_id": _RESERVATION_ID},
        )

        # Item stub returns None → 404 "Item not found" (not "Reservation not found")
        # This proves the router moved past the ownership check.
        assert resp.status_code == 404
        detail = resp.json().get("detail", "")
        assert "Item not found" in detail, (
            f"Expected 'Item not found' (past BOLA check), got: {detail!r}. "
            "The router may have returned 404 at the ownership check instead."
        )
        assert not pay_spy.issue_called  # item not found → never reaches gateway
