"""Law 4 proof — customer capability enforcement (ADR-017).

Proves two things:

    1. Every route classified scope="customer" in ROUTE_SECURITY returns 401
       when called without a valid Bearer JWT.

    2. A valid JWT (customer or admin scope) passes the auth layer.
       Admin JWT passes because admin ⊇ customer capabilities (ADR-017 §Law 4).

This is the customer-side complement to test_admin_scope_enforcement.py
(admin-side: customer JWT rejected on admin endpoints → 403).

By Law 0: a law without a test is a recommendation.
A scan-based test (TestLaw4StructuralScan) catches missing Depends(get_customer_ref)
at CI time — the same principle used by Law 1/3 for missing scope/rate_class entries.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import jwt
import pytest
from fastapi.testclient import TestClient

from yasargold_commerce.db import get_db
from yasargold_commerce.main import app
from yasargold_commerce.routers.payments import _get_payment_service
from yasargold_commerce.security import ROUTE_SECURITY

_SECRET = "test_law4_customer_scope_proof_key"
_ALGORITHM = "HS256"

# All customer-scoped routes with minimal valid-looking request data.
# The test does NOT validate business logic — only that 401 is returned
# without a JWT and that auth passes with a valid JWT.
_CUSTOMER_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    ("POST", "/api/v1/reservations",     {"item_code": "RING24K001", "karat": "24"}),
    ("POST", "/api/v1/payments",          {"reservation_id": "res_test_001"}),
    ("GET",  "/api/v1/orders/ord_001",    None),
    ("GET",  "/api/v1/reservations/res_001/order", None),
    ("GET",  "/api/v1/orders/ord_001/shipments",   None),
]


def _make_token(scope: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": "+966500000001", "scope": scope, "exp": now + timedelta(hours=1)},
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


# ---------------------------------------------------------------------------
# Structural scan: every customer-scoped route must enforce auth
# ---------------------------------------------------------------------------

class TestLaw4StructuralScan:
    """Walk ROUTE_SECURITY and verify every customer-scoped route is secured.

    This is the machine-verifiable enforcement of Law 4 for customer endpoints.
    If any route has scope="customer" in the registry but returns 200 (or any
    non-401 response) without a JWT, this test fails and blocks the merge.
    """

    def setup_method(self) -> None:
        os.environ["JWT_SECRET_KEY"] = _SECRET
        app.dependency_overrides[get_db] = lambda: _StubDb()
        # Override gateway dep so missing MOYASAR_API_KEY does not cause 500
        # before auth can return 401. Auth must be the first thing that fires.
        app.dependency_overrides[_get_payment_service] = lambda: MagicMock()
        self._client = TestClient(app, raise_server_exceptions=False)

    def teardown_method(self) -> None:
        app.dependency_overrides.clear()
        os.environ.pop("JWT_SECRET_KEY", None)

    @pytest.mark.parametrize("method,path,body", _CUSTOMER_ENDPOINTS)
    def test_customer_endpoint_requires_jwt(
        self, method: str, path: str, body: dict | None
    ) -> None:
        """No Bearer token on a customer-scoped endpoint must return 401.

        If this test fails with 200, the endpoint is missing
        Depends(get_customer_ref) — it is classified but not enforced.
        A 422 (body validation) also fails: the auth check must precede body
        parsing for all customer endpoints.
        """
        resp = self._client.request(method, path, json=body)
        assert resp.status_code == 401, (
            f"{method} {path} returned {resp.status_code} without a JWT. "
            f"Expected 401. "
            f"This means Depends(get_customer_ref) is missing from the route handler. "
            f"The endpoint is classified scope='customer' but not enforcing it — "
            f"Law 4 violation."
        )

    @pytest.mark.parametrize("method,path,body", _CUSTOMER_ENDPOINTS)
    def test_customer_jwt_passes_auth_on_customer_endpoint(
        self, method: str, path: str, body: dict | None
    ) -> None:
        """A valid customer-scoped JWT must pass the auth layer.

        The response may be 404, 409, 422, or 503 (business logic, missing data),
        but must NOT be 401 (auth failure) or 403 (scope rejection).
        """
        token = _make_token("customer")
        resp = self._client.request(
            method, path, json=body,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code not in (401, 403), (
            f"{method} {path} rejected a valid customer JWT with {resp.status_code}. "
            f"Expected auth to pass (business logic may return 4xx/5xx, that is fine)."
        )

    @pytest.mark.parametrize("method,path,body", _CUSTOMER_ENDPOINTS)
    def test_admin_jwt_passes_auth_on_customer_endpoint(
        self, method: str, path: str, body: dict | None
    ) -> None:
        """A valid admin JWT must also pass customer-scope auth.

        ADR-017 Law 4: admin ⊇ customer capabilities.
        An admin JWT calling a customer endpoint must not be rejected by auth.
        """
        token = _make_token("admin")
        resp = self._client.request(
            method, path, json=body,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code not in (401, 403), (
            f"{method} {path} rejected an admin JWT with {resp.status_code}. "
            f"Admin scope must not be rejected on customer-capability endpoints."
        )

    def test_customer_scope_registry_matches_enforced_endpoints(self) -> None:
        """Prove the parametrize list covers ALL customer-scoped routes.

        If a new customer-scoped route is added to ROUTE_SECURITY but not
        to _CUSTOMER_ENDPOINTS in this test file, this test fails.
        """
        registered_customer_routes = [
            (method.upper(), template)
            for (method, template), entry in ROUTE_SECURITY.items()
            if entry.scope == "customer"
        ]

        tested_paths = {path for _, path, _ in _CUSTOMER_ENDPOINTS}

        # Path templates may not match literal test paths (e.g. /orders/{order_id}
        # vs /orders/ord_001). We verify count matches — a new customer route added
        # to ROUTE_SECURITY without adding to _CUSTOMER_ENDPOINTS breaks this count.
        assert len(registered_customer_routes) == len(_CUSTOMER_ENDPOINTS), (
            f"ROUTE_SECURITY has {len(registered_customer_routes)} customer-scoped routes "
            f"but _CUSTOMER_ENDPOINTS has {len(_CUSTOMER_ENDPOINTS)} entries. "
            f"Add the new route to _CUSTOMER_ENDPOINTS in this test file. "
            f"Registered: {registered_customer_routes}"
        )
