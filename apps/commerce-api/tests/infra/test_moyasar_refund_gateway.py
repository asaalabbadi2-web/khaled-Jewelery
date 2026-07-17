"""Unit tests for MoyasarRefundGateway — zero network calls.

ADR-019 requirements verified:
  ① Timeout       — httpx.TimeoutException → RefundTransientError
  ② Retry         — 5xx retried 3 times; 4xx not retried (single call)
  ③ Idempotency   — Idempotency-Key header equals str(intent.id)
  ④ Correlation   — X-Correlation-Id present in every request; logged at INFO
  ⑤ Metrics       — PAYMENT_REFUND_SUCCESS / FAILURE counters increment
  ⑥ Probe         — probe() returns True on HTTP response, False on network error

HTTP mapping (cross-cutting):
  200 → success (return None)
  202 → RefundTransientError (no adapter retry)
  400 / 401 / 404 / 409 → RefundPermanentError
  429 → RefundTransientError (adapter retries)
  503 → RefundTransientError (adapter retries)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest

from yasargold_domain.payment.intent import PaymentIntent, PaymentStatus
from yasargold_domain.payment.refund_gateway import RefundPermanentError, RefundTransientError
from yasargold_domain.shared.identifiers import PaymentIntentId, ReservationId

from yasargold_commerce.infra.moyasar_refund_gateway import MoyasarRefundGateway
from yasargold_commerce.metrics import (
    PAYMENT_REFUND_DURATION,
    PAYMENT_REFUND_FAILURE,
    PAYMENT_REFUND_SUCCESS,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_API_KEY = "pk_test_abc123"
_NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)
_INTENT_ID = PaymentIntentId("pi_test0001abc12345")
_RES_ID = ReservationId("res_abc123")
_AMOUNT = Decimal("5500.00")
_PROVIDER_REF = "pay_moyasar_ref001"


def _make_intent() -> PaymentIntent:
    return PaymentIntent(
        id=_INTENT_ID,
        reservation_id=_RES_ID,
        amount=_AMOUNT,
        currency="SAR",
        status=PaymentStatus.REFUND_PENDING,
        created_at=_NOW,
        expires_at=_NOW,
        provider_reference=_PROVIDER_REF,
    )


def _make_response(status_code: int, body: dict | None = None) -> httpx.Response:
    content = json.dumps(body or {"id": "refund_001", "status": "refunded"}).encode()
    return httpx.Response(
        status_code=status_code,
        content=content,
        headers={"Content-Type": "application/json"},
    )


def _make_gateway(responses: list[httpx.Response]) -> tuple[MoyasarRefundGateway, list]:
    """Return (gateway, captured_requests). Responses consumed in order."""
    captured: list[httpx.Request] = []
    idx = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal idx
        captured.append(request)
        resp = responses[idx]
        idx = min(idx + 1, len(responses) - 1)
        return resp

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://api.moyasar.com/v1")
    return MoyasarRefundGateway(api_key=_API_KEY, client=client), captured


def _make_raise_gateway(exc: Exception) -> MoyasarRefundGateway:
    """Return a gateway whose client always raises exc on POST."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://api.moyasar.com/v1")
    return MoyasarRefundGateway(api_key=_API_KEY, client=client)


# ===========================================================================
# ADR-019 Requirement ① — Timeout → RefundTransientError
# ===========================================================================

class TestTimeout:
    def test_timeout_raises_transient(self):
        """httpx.TimeoutException → RefundTransientError (not bubbled as httpx error)."""
        gw = _make_raise_gateway(httpx.ReadTimeout("timed out", request=None))
        with patch("yasargold_commerce.infra.moyasar_refund_gateway.time.sleep"):
            with pytest.raises(RefundTransientError):
                gw.refund(_make_intent())

    def test_connect_error_raises_transient(self):
        """httpx.ConnectError → RefundTransientError."""
        gw = _make_raise_gateway(httpx.ConnectError("connection refused"))
        with patch("yasargold_commerce.infra.moyasar_refund_gateway.time.sleep"):
            with pytest.raises(RefundTransientError):
                gw.refund(_make_intent())


# ===========================================================================
# ADR-019 Requirement ② — Retry: 5xx retried, 4xx not retried
# ===========================================================================

class TestRetry:
    def test_5xx_retried_three_times_then_raises(self):
        """5xx → retried up to MAX_RETRIES times, then raises RefundTransientError."""
        gw, captured = _make_gateway([_make_response(503)] * 3)
        with patch("yasargold_commerce.infra.moyasar_refund_gateway.time.sleep"):
            with pytest.raises(RefundTransientError):
                gw.refund(_make_intent())
        assert len(captured) == 3

    def test_5xx_retried_then_success(self):
        """5xx on first two attempts, 200 on third → success (no exception)."""
        gw, captured = _make_gateway([
            _make_response(503),
            _make_response(503),
            _make_response(200),
        ])
        with patch("yasargold_commerce.infra.moyasar_refund_gateway.time.sleep"):
            gw.refund(_make_intent())  # must not raise
        assert len(captured) == 3

    def test_429_retried(self):
        """429 is transient — adapter retries (unlike most 4xx)."""
        gw, captured = _make_gateway([
            _make_response(429),
            _make_response(200),
        ])
        with patch("yasargold_commerce.infra.moyasar_refund_gateway.time.sleep"):
            gw.refund(_make_intent())
        assert len(captured) == 2

    def test_4xx_not_retried(self):
        """400/401/404/409 → RefundPermanentError on the first attempt (no retry)."""
        for status in (400, 401, 404, 409):
            gw, captured = _make_gateway([_make_response(status)])
            with pytest.raises(RefundPermanentError):
                gw.refund(_make_intent())
            assert len(captured) == 1, f"status {status} should not be retried"


# ===========================================================================
# ADR-019 Requirement ③ — Idempotency-Key header
# ===========================================================================

class TestIdempotencyKey:
    def test_idempotency_key_equals_intent_id(self):
        """Idempotency-Key header must be str(intent.id) on every attempt."""
        intent = _make_intent()
        gw, captured = _make_gateway([_make_response(200)])
        gw.refund(intent)
        assert len(captured) == 1
        assert captured[0].headers["Idempotency-Key"] == str(intent.id)

    def test_idempotency_key_stable_across_retries(self):
        """Same Idempotency-Key on every retry attempt — enables safe retry."""
        intent = _make_intent()
        gw, captured = _make_gateway([_make_response(503), _make_response(200)])
        with patch("yasargold_commerce.infra.moyasar_refund_gateway.time.sleep"):
            gw.refund(intent)
        keys = [r.headers["Idempotency-Key"] for r in captured]
        assert keys[0] == keys[1] == str(intent.id)


# ===========================================================================
# ADR-019 Requirement ④ — Correlation ID in every request + logs
# ===========================================================================

class TestCorrelationId:
    def test_correlation_id_in_request_header(self):
        """X-Correlation-Id must be present on every outbound request."""
        gw, captured = _make_gateway([_make_response(200)])
        gw.refund(_make_intent())
        assert "X-Correlation-Id" in captured[0].headers
        # Must be a non-empty string (uuid4 format)
        assert len(captured[0].headers["X-Correlation-Id"]) == 36

    def test_correlation_id_in_log(self, caplog):
        """Correlation ID must appear in the INFO log for incident tracing."""
        import logging
        gw, captured = _make_gateway([_make_response(200)])
        with caplog.at_level(logging.INFO, logger="yasargold_commerce.infra.moyasar_refund_gateway"):
            gw.refund(_make_intent())

        correlation_id = captured[0].headers["X-Correlation-Id"]
        assert any(correlation_id in record.getMessage() for record in caplog.records)

    def test_correlation_id_stable_across_retries(self):
        """Same correlation ID on all retry attempts — one incident, one trace."""
        gw, captured = _make_gateway([_make_response(503), _make_response(200)])
        with patch("yasargold_commerce.infra.moyasar_refund_gateway.time.sleep"):
            gw.refund(_make_intent())
        ids = [r.headers["X-Correlation-Id"] for r in captured]
        assert ids[0] == ids[1]


# ===========================================================================
# ADR-019 Requirement ⑤ — Metrics
# ===========================================================================

class TestMetrics:
    def test_success_counter_increments(self, monkeypatch):
        """PAYMENT_REFUND_SUCCESS.inc() called on 200 response."""
        called = []
        monkeypatch.setattr(PAYMENT_REFUND_SUCCESS, "inc", lambda: called.append(1))
        gw, _ = _make_gateway([_make_response(200)])
        gw.refund(_make_intent())
        assert called == [1]

    def test_failure_counter_permanent(self, monkeypatch):
        """PAYMENT_REFUND_FAILURE.labels(kind='permanent').inc() on 409."""
        recorded = []
        original_labels = PAYMENT_REFUND_FAILURE.labels

        def fake_labels(**kwargs):
            class _FakeCounter:
                def inc(self_inner):
                    recorded.append(kwargs)
            return _FakeCounter()

        monkeypatch.setattr(PAYMENT_REFUND_FAILURE, "labels", fake_labels)
        gw, _ = _make_gateway([_make_response(409)])
        with pytest.raises(RefundPermanentError):
            gw.refund(_make_intent())
        assert recorded == [{"kind": "permanent"}]

    def test_failure_counter_transient(self, monkeypatch):
        """PAYMENT_REFUND_FAILURE.labels(kind='transient').inc() on all-retries-exhausted."""
        recorded = []

        def fake_labels(**kwargs):
            class _FakeCounter:
                def inc(self_inner):
                    recorded.append(kwargs)
            return _FakeCounter()

        monkeypatch.setattr(PAYMENT_REFUND_FAILURE, "labels", fake_labels)
        gw, _ = _make_gateway([_make_response(503)] * 3)
        with patch("yasargold_commerce.infra.moyasar_refund_gateway.time.sleep"):
            with pytest.raises(RefundTransientError):
                gw.refund(_make_intent())
        assert {"kind": "transient"} in recorded

    def test_duration_observed(self, monkeypatch):
        """PAYMENT_REFUND_DURATION.observe() called with a non-negative value."""
        observed = []
        monkeypatch.setattr(PAYMENT_REFUND_DURATION, "observe", lambda v: observed.append(v))
        gw, _ = _make_gateway([_make_response(200)])
        gw.refund(_make_intent())
        assert len(observed) == 1
        assert observed[0] >= 0


# ===========================================================================
# ADR-019 Requirement ⑥ — Health probe
# ===========================================================================

class TestProbe:
    def test_probe_returns_true_on_http_response(self):
        """Any HTTP response (including 404) → True (API is reachable)."""
        gw, _ = _make_gateway([_make_response(404)])
        assert gw.probe() is True

    def test_probe_returns_false_on_network_error(self):
        """Network failure → False (API is unreachable)."""
        gw = _make_raise_gateway(httpx.ConnectError("connection refused"))
        assert gw.probe() is False

    def test_probe_returns_false_on_timeout(self):
        """Timeout → False."""
        gw = _make_raise_gateway(httpx.ReadTimeout("timed out", request=None))
        assert gw.probe() is False


# ===========================================================================
# HTTP status → domain exception mapping
# ===========================================================================

class TestHttpMapping:
    def test_200_returns_none(self):
        """200 → method returns None (success)."""
        gw, _ = _make_gateway([_make_response(200)])
        result = gw.refund(_make_intent())
        assert result is None

    def test_202_raises_transient_no_retry(self):
        """202 → RefundTransientError immediately (no retry — RefundWorker handles)."""
        gw, captured = _make_gateway([_make_response(202)])
        with pytest.raises(RefundTransientError, match="202"):
            gw.refund(_make_intent())
        assert len(captured) == 1  # no retry

    @pytest.mark.parametrize("status", [400, 401, 404, 409])
    def test_permanent_status_codes(self, status: int):
        """400/401/404/409 → RefundPermanentError."""
        gw, _ = _make_gateway([_make_response(status)])
        with pytest.raises(RefundPermanentError):
            gw.refund(_make_intent())

    def test_503_raises_transient_after_retries(self):
        """503 → retried then RefundTransientError."""
        gw, _ = _make_gateway([_make_response(503)] * 3)
        with patch("yasargold_commerce.infra.moyasar_refund_gateway.time.sleep"):
            with pytest.raises(RefundTransientError):
                gw.refund(_make_intent())

    def test_no_http_exception_raised(self):
        """Adapter never raises HTTPException — only domain exceptions cross the boundary."""
        from fastapi import HTTPException
        gw, _ = _make_gateway([_make_response(500)] * 3)
        with patch("yasargold_commerce.infra.moyasar_refund_gateway.time.sleep"):
            with pytest.raises(Exception) as exc_info:
                gw.refund(_make_intent())
        assert not isinstance(exc_info.value, HTTPException)
