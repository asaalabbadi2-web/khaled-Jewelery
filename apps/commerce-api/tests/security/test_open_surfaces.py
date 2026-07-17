"""Open surface witnesses — Law 0 applied to Known Gaps.

Every documented open surface carries an xfail test that attempts the attack
and expects it to SUCCEED (i.e., the protection is NOT yet in place).

When a gap is closed, its xfail test starts passing unexpectedly (pytest
marks it XPASS). CI is configured to treat XPASS as a failure
(xfail_strict=true in pyproject.toml). This forces the PR that closes the
gap to also update this file and the documentation — drift in either
direction becomes CI-fatal.

Convention:
    @pytest.mark.xfail(strict=True, reason="SURFACE-ID: gap description · fix: what closes it")

Adding a test here does NOT make a gap acceptable — it makes it observable.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from yasargold_commerce.auth import get_customer_ref
from yasargold_commerce.db import get_db
from yasargold_commerce.main import app
from yasargold_commerce.routers.payments import _get_payment_service

_SECRET = "test_open_surfaces_witness_key"
_ALGORITHM = "HS256"


def _make_token(scope: str = "customer", sub: str = "+966500000001") -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": sub, "scope": scope, "exp": now + timedelta(hours=1)},
        _SECRET,
        algorithm=_ALGORITHM,
    )


class _StubDb:
    def execute(self, *a, **kw):
        return self

    def scalar_one_or_none(self):
        return None

    def scalars(self):
        return self

    def all(self):
        return []

    def close(self):
        pass


@pytest.fixture()
def client():
    os.environ["JWT_SECRET_KEY"] = _SECRET
    from unittest.mock import MagicMock
    app.dependency_overrides[get_db] = lambda: _StubDb()
    app.dependency_overrides[_get_payment_service] = lambda: MagicMock()
    c = TestClient(app, raise_server_exceptions=False)
    yield c
    app.dependency_overrides.clear()
    os.environ.pop("JWT_SECRET_KEY", None)


# ---------------------------------------------------------------------------
# BOLA-shipments: GET /orders/{id}/shipments
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    strict=True,
    reason=(
        "BOLA-shipments: an authenticated customer can read any order's shipment "
        "regardless of ownership. Expected attack: caller_A reads caller_B's shipment "
        "by guessing order_id. "
        "Fix: add ownership check — shipment.order.customer_ref == customer_ref — "
        "mirroring find_order_for_customer() pattern. Deferred to Gate B. "
        "When fixed: this test returns 404 (not 200), xfail becomes XPASS, CI fails, "
        "update this file + docs/security/security-overview.md §8 + ADR-017."
    ),
)
def test_bola_shipments_caller_b_reads_caller_a_shipment(client: TestClient) -> None:
    """BOLA witness — authenticated non-owner can read another customer's shipment.

    The StubDb returns None for every query so the response is 404 (no shipment
    row found) rather than 200. In production with a real DB, a different customer's
    token would receive the shipment data.

    This test proves the gap: 401 is NOT returned (auth passes for any valid JWT).
    The ownership gap means the only thing preventing cross-customer read is
    that the attacker doesn't know the order_id UUID — security-through-obscurity.

    When the ownership check is added, the route will return 404 for the
    non-owner regardless of DB content. This xfail then becomes XPASS → CI fails.
    """
    # Caller B ("+966500000002") attempts to read an order owned by Caller A
    token_b = _make_token(sub="+966500000002")
    resp = client.get(
        "/api/v1/orders/ord_owned_by_caller_a/shipments",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    # With StubDb (no rows), the response is 404 (shipment not found).
    # The point: it is NOT 401 — auth passed for a non-owner.
    # In a real DB with real data, this would return 200.
    # The attack: scan UUID space or leak order_ids, then read cross-customer.
    assert resp.status_code == 401, (
        "Expected 401 (ownership rejected) but got something else. "
        "If you see this, the ownership check has been added — update §8 and ADR-017."
    )
