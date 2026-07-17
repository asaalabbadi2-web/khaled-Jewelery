"""Law 6 — No domain translation before signature verification (ADR-017).

ADR-010 established that the webhook handler is a translator, not a decision
maker. Law 6 adds the security invariant: translation must not begin until
the provider's signature is verified.

If the handler parses the payload before verifying the signature:
    - A forged payload (wrong signature) reaches domain logic
    - An attacker can drive state transitions without Moyasar's involvement

Law 6 proof:
    A forged webhook with a wrong signature must return HTTP 400
    and must NOT call the domain PaymentService.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from yasargold_commerce.db import get_db
from yasargold_commerce.main import app
from yasargold_commerce.routers.payments import (
    _get_checkout_uow,
    _get_gateway,
    _get_payment_service,
    _get_payment_uow,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SECRET_KEY = "test_webhook_secret_law6"
_WRONG_KEY = "wrong_secret_this_should_fail"
_PROVIDER_REF = "pay_law6_test_001"

_PAID_PAYLOAD = json.dumps({
    "id": _PROVIDER_REF,
    "status": "paid",
    "amount": 550000,
    "currency": "SAR",
    "source": {"type": "creditcard"},
    "metadata": {"intent_id": "pi_law6_001"},
}).encode()


def _sign(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

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


def _real_gateway(secret: str = _SECRET_KEY) -> Any:
    from yasargold_commerce.infra.moyasar_gateway import MoyasarGateway
    return MoyasarGateway(api_key="pk_test", secret_key=secret)


@dataclass
class _SpyPaymentService:
    transition_called: bool = False

    def confirm(self, *a: Any, **kw: Any) -> Any:
        self.transition_called = True
        from yasargold_domain.payment.exceptions import PaymentIntentNotFoundException
        raise PaymentIntentNotFoundException(_PROVIDER_REF)

    def issue(self, *a: Any, **kw: Any) -> Any:
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


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

def _make_client(
    secret: str = _SECRET_KEY,
) -> tuple[TestClient, _SpyPaymentService]:
    spy = _SpyPaymentService()
    gw = _real_gateway(secret)
    fake_uow = _FakeUoW()
    stub_db = _StubDb()

    app.dependency_overrides[get_db] = lambda: stub_db
    app.dependency_overrides[_get_gateway] = lambda: gw
    app.dependency_overrides[_get_payment_service] = lambda: spy
    app.dependency_overrides[_get_payment_uow] = lambda: fake_uow
    app.dependency_overrides[_get_checkout_uow] = lambda: fake_uow

    client = TestClient(app, raise_server_exceptions=False)
    return client, spy


# ---------------------------------------------------------------------------
# Law 6 tests
# ---------------------------------------------------------------------------

class TestLaw6WebhookSignatureVerification:
    def teardown_method(self) -> None:
        app.dependency_overrides.clear()

    def test_valid_signature_reaches_domain(self) -> None:
        """A correctly signed webhook calls the domain PaymentService."""
        client, spy = _make_client()
        signature = _sign(_PAID_PAYLOAD, _SECRET_KEY)

        resp = client.post(
            "/api/v1/webhooks/payment",
            content=_PAID_PAYLOAD,
            headers={"X-Moyasar-Signature": signature, "Content-Type": "application/json"},
        )

        # 404 is expected because the spy raises PaymentIntentNotFoundException —
        # the important thing is that the domain was reached.
        assert resp.status_code in (204, 404)
        assert spy.transition_called, "Domain service must be called for valid signature"

    def test_wrong_signature_returns_400(self) -> None:
        """A forged webhook with wrong signature must return 400."""
        client, spy = _make_client()
        wrong_signature = _sign(_PAID_PAYLOAD, _WRONG_KEY)

        resp = client.post(
            "/api/v1/webhooks/payment",
            content=_PAID_PAYLOAD,
            headers={"X-Moyasar-Signature": wrong_signature, "Content-Type": "application/json"},
        )

        assert resp.status_code == 400

    def test_forged_payload_does_not_reach_domain_service(self) -> None:
        """Core Law 6 proof: domain service must NOT be called before signature check.

        An attacker who sends a forged payload must be stopped before any
        state transition can occur.
        """
        client, spy = _make_client()
        wrong_signature = _sign(_PAID_PAYLOAD, _WRONG_KEY)

        client.post(
            "/api/v1/webhooks/payment",
            content=_PAID_PAYLOAD,
            headers={"X-Moyasar-Signature": wrong_signature, "Content-Type": "application/json"},
        )

        assert not spy.transition_called, (
            "Domain service must NOT be called when signature is invalid. "
            "If this fails, the handler is parsing before verifying — Law 6 is violated."
        )

    def test_missing_signature_header_is_rejected(self) -> None:
        """Missing X-Moyasar-Signature header must be rejected before any processing."""
        client, spy = _make_client()

        resp = client.post(
            "/api/v1/webhooks/payment",
            content=_PAID_PAYLOAD,
            headers={"Content-Type": "application/json"},
        )

        # FastAPI rejects missing required Header() with 422 or handler returns 400
        assert resp.status_code in (400, 422)
        assert not spy.transition_called
