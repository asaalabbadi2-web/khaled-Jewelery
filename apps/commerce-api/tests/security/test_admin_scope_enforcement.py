"""SEC-001 withdrawal condition proof test (ADR-017).

This test is the machine-verifiable proof that satisfies SEC-001 withdrawal
condition (2) from ADR-017:

    "A test proves that admin endpoints reject a valid JWT that does not carry
     the admin scope claim."

Until this test passes, require_admin_secret must remain active.
Now that it passes, SEC-001 is considered closed for admin endpoints.

Invariant: a valid JWT with scope="customer" must NOT be able to call
any admin-scoped endpoint. The only acceptable responses are 401 or 403.

If any admin endpoint returns 200, 201, 404, 409, 502, or 503 on a
customer-scoped JWT, that endpoint is unprotected and this test fails.

Admin endpoints under test:
    POST /api/v1/orders/{order_id}/shipments
    POST /api/v1/shipments/{shipment_id}/void
    POST /api/v1/shipments/{shipment_id}/deliver
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from yasargold_commerce.db import get_db
from yasargold_commerce.main import app

_SECRET = "test_sec001_withdrawal_proof"
_ALGORITHM = "HS256"

_ADMIN_ENDPOINTS: list[tuple[str, str, dict]] = [
    ("POST", "/api/v1/orders/ord_test_001/shipments", {"carrier_id": "aramex"}),
    ("POST", "/api/v1/shipments/shp_test_001/void", {}),
    ("POST", "/api/v1/shipments/shp_test_001/deliver", {}),
]


def _customer_jwt() -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": "+966500000001", "scope": "customer", "exp": now + timedelta(hours=1)},
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


class TestSec001WithdrawalCondition:
    """Proof that condition (2) of SEC-001 withdrawal is satisfied."""

    def setup_method(self) -> None:
        os.environ["JWT_SECRET_KEY"] = _SECRET
        app.dependency_overrides[get_db] = lambda: _StubDb()
        self._client = TestClient(app, raise_server_exceptions=False)

    def teardown_method(self) -> None:
        app.dependency_overrides.clear()
        os.environ.pop("JWT_SECRET_KEY", None)

    @pytest.mark.parametrize("method,path,body", _ADMIN_ENDPOINTS)
    def test_customer_jwt_rejected_on_admin_endpoint(
        self, method: str, path: str, body: dict
    ) -> None:
        """A customer-scoped JWT must not be accepted by admin endpoints.

        This test proves SEC-001 withdrawal condition (2):
        admin endpoints reject a valid JWT without the admin scope.
        """
        token = _customer_jwt()
        resp = self._client.request(
            method,
            path,
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code in (401, 403), (
            f"{method} {path} returned {resp.status_code} for customer-scoped JWT. "
            f"Expected 401 or 403. "
            f"This means the endpoint is not enforcing admin scope — SEC-001 withdrawal "
            f"condition (2) is NOT satisfied. Check that Depends(require_admin) is wired."
        )

    @pytest.mark.parametrize("method,path,body", _ADMIN_ENDPOINTS)
    def test_no_bearer_token_rejected_on_admin_endpoint(
        self, method: str, path: str, body: dict
    ) -> None:
        """Missing auth header must be rejected with 401."""
        resp = self._client.request(method, path, json=body)
        assert resp.status_code == 401, (
            f"{method} {path} returned {resp.status_code} with no auth header. "
            f"Expected 401."
        )

    def test_admin_jwt_is_accepted_structurally(self) -> None:
        """A valid admin JWT must pass the auth check (may fail further in the stack).

        This test is not about business logic — it only proves the auth layer
        accepts the correct credential structure. The 404/409/502 from downstream
        is expected (no real DB/carrier in this test harness).
        """
        now = datetime.now(timezone.utc)
        admin_token = jwt.encode(
            {"sub": "admin_user_001", "scope": "admin", "exp": now + timedelta(hours=1)},
            _SECRET,
            algorithm=_ALGORITHM,
        )
        resp = self._client.post(
            "/api/v1/orders/ord_nonexistent/shipments",
            json={"carrier_id": "aramex"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        # Auth passes (not 401/403). Business logic may return 404 (order not found),
        # 503 (DB), or similar — all of these mean the admin scope was accepted.
        assert resp.status_code not in (401, 403), (
            f"Admin JWT was rejected with {resp.status_code}. "
            f"The auth layer should accept scope=admin."
        )
