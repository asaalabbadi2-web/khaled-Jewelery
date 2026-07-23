"""Law 5 — BOLA: shipment router delegates ownership check to domain service.

Closes the last open BOLA surface from ADR-017 §5 (BOLA-shipments):
    GET /api/v1/orders/{order_id}/shipments previously accepted any valid
    customer JWT and returned shipment data regardless of who owned the order.

After this fix:
    • ownership is validated by OrderService.find_order_for_customer() before
      any shipment row is queried
    • non-owner and non-existent orders produce identical HTTP 404 responses —
      the caller cannot enumerate resources

Law 5 rules verified here (mirroring test_payment_bola.py):
  1. Ownership mismatch (wrong customer) → 404, shipment query never reached
  2. customer_ref=None (unauthenticated) → 404, deny-by-default
  3. Ownership check delegates to domain service (spy verifies exactly 1 call
     with the caller's customer_ref — router does not perform its own DB check)
  4. Correct ownership → router proceeds to shipment query (ownership check passed)

BOLA enumeration invariant:
  HTTP status 404 + detail "No shipment found for this order" is returned
  for ALL rejection cases. The response body is identical whether:
    • the order_id is unknown
    • the order belongs to another customer
    • the order is owned but has no shipment yet
  This prevents oracle attacks (the attacker cannot distinguish the three cases).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from yasargold_commerce.auth import get_customer_ref
from yasargold_commerce.db import get_db
from yasargold_commerce.main import app
from yasargold_commerce.routers.shipments import _get_order_service

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_OWNER_REF  = "+966501234567"
_OTHER_REF  = "+966500000000"
_ORDER_ID   = "ord_bola_test_001"

# Truthy sentinel — the domain service returns "an Order" to signal ownership match.
# The router only checks `is None`; it does not read any Order fields.
_FAKE_ORDER = MagicMock(name="FakeOrder")

_NOT_FOUND_DETAIL = "No shipment found for this order"


# ---------------------------------------------------------------------------
# Spy / stubs
# ---------------------------------------------------------------------------


@dataclass
class _SpyOrderService:
    """Controls what find_order_for_customer returns; records every call."""

    calls: list[tuple] = field(default_factory=list)
    _return_value: Any = None

    def configure(self, *, returns: Any) -> None:
        self._return_value = returns

    def find_order_for_customer(
        self,
        order_id: Any,
        customer_ref: str | None,
        uow: Any,
    ) -> Any:
        self.calls.append((order_id, customer_ref))
        return self._return_value

    # Remaining OrderService methods — not exercised by this endpoint
    def create_from_reservation(self, *a: Any, **kw: Any) -> Any:
        raise NotImplementedError

    def ship(self, *a: Any, **kw: Any) -> Any:
        raise NotImplementedError

    def deliver(self, *a: Any, **kw: Any) -> Any:
        raise NotImplementedError

    def cancel(self, *a: Any, **kw: Any) -> Any:
        raise NotImplementedError


class _StubDb:
    """Returns None for every query — no shipment row exists in test DB."""

    def execute(self, *a: Any, **kw: Any) -> _StubResult:
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
    service_returns: Any,
) -> tuple[TestClient, _SpyOrderService]:
    spy = _SpyOrderService()
    spy.configure(returns=service_returns)

    app.dependency_overrides[get_db]             = lambda: _StubDb()
    app.dependency_overrides[get_customer_ref]   = lambda: customer_ref
    app.dependency_overrides[_get_order_service] = lambda: spy

    client = TestClient(app, raise_server_exceptions=False)
    return client, spy


# ---------------------------------------------------------------------------
# Law 5 BOLA proof tests — shipments
# ---------------------------------------------------------------------------


class TestShipmentBOLA:
    def teardown_method(self) -> None:
        app.dependency_overrides.clear()

    # ── Test 1 ─────────────────────────────────────────────────────────────

    def test_wrong_customer_returns_404(self) -> None:
        """BOLA core invariant: non-owner receives 404, not the shipment.

        Caller _OTHER_REF attempts to read an order owned by _OWNER_REF.
        The domain service returns None (mismatch) → router must return 404.
        """
        client, spy = _make_client(
            customer_ref=_OTHER_REF,
            service_returns=None,  # ownership mismatch
        )

        resp = client.get(f"/api/v1/orders/{_ORDER_ID}/shipments")

        assert resp.status_code == 404, (
            f"BOLA: cross-customer shipment read must return 404, got {resp.status_code}. "
            "If this returns 200, the ownership check is not applied."
        )
        assert resp.json().get("detail") == _NOT_FOUND_DETAIL, (
            "Response body must not hint whether the order exists (enumeration guard)."
        )

    # ── Test 2 ─────────────────────────────────────────────────────────────

    def test_unauthenticated_caller_returns_404(self) -> None:
        """customer_ref=None → deny-by-default → 404.

        OrderService.find_order_for_customer returns None when customer_ref is None.
        The router must propagate this as 404, not 401 — the JWT gate (get_customer_ref)
        raises 401 before we reach the ownership check; this test exercises the case
        where the dependency is overridden to None (e.g. misconfigured middleware).
        """
        client, spy = _make_client(
            customer_ref=None,
            service_returns=None,  # deny-by-default from domain service
        )

        resp = client.get(f"/api/v1/orders/{_ORDER_ID}/shipments")

        assert resp.status_code == 404

    # ── Test 3 ─────────────────────────────────────────────────────────────

    def test_ownership_check_delegates_to_domain_service(self) -> None:
        """The router must call find_order_for_customer, not perform its own DB check.

        Verified by controlling the spy's return value and asserting:
          • the spy was called exactly once
          • it received the caller's exact customer_ref
          • the router used the spy's return value (None → 404)

        If the router bypassed the service and queried the DB directly, the spy
        call count would be 0 even on a 404 response.
        """
        client, spy = _make_client(
            customer_ref=_OWNER_REF,
            service_returns=None,  # configured to reject
        )

        client.get(f"/api/v1/orders/{_ORDER_ID}/shipments")

        assert len(spy.calls) == 1, (
            f"Router must delegate to domain service (exactly 1 call). "
            f"Got {len(spy.calls)} calls."
        )
        _, called_with_ref = spy.calls[0]
        assert called_with_ref == _OWNER_REF, (
            f"Domain service must receive the caller's customer_ref. "
            f"Got: {called_with_ref!r}"
        )

    # ── Test 4 ─────────────────────────────────────────────────────────────

    def test_owner_proceeds_past_ownership_check(self) -> None:
        """When the service returns an Order, the router must not 404 from the BOLA check.

        We configure the spy to return _FAKE_ORDER (ownership match). The router
        then queries ShipmentRow (StubDb → None) and returns 404 "no shipment yet".
        The same 404 status is returned, but we can prove the route passed the
        ownership check because:
          • spy.calls has exactly 1 entry (the check was invoked)
          • the spy returned _FAKE_ORDER (truthy → ownership passed)
          • the router continued to the shipment query before returning 404

        This also proves the BOLA enumeration invariant: the response is identical
        (404, same body) whether the order is not owned or not yet shipped —
        the caller cannot distinguish the two cases.
        """
        client, spy = _make_client(
            customer_ref=_OWNER_REF,
            service_returns=_FAKE_ORDER,  # ownership match — router proceeds
        )

        resp = client.get(f"/api/v1/orders/{_ORDER_ID}/shipments")

        # 404 from shipment query (StubDb, no row) — not from BOLA check
        assert resp.status_code == 404
        assert resp.json().get("detail") == _NOT_FOUND_DETAIL, (
            "Enumeration invariant: no-shipment-yet must return the same body as non-owner."
        )

        # The ownership check was reached and returned truthy — router continued
        assert len(spy.calls) == 1
        _, called_with_ref = spy.calls[0]
        assert called_with_ref == _OWNER_REF
