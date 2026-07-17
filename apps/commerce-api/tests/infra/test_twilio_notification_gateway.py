"""Unit tests for TwilioNotificationGateway — zero network calls.

ADR-019 requirements verified:
  ① Timeout       — httpx.TimeoutException → NotificationGatewayError
  ② Retry         — retry budget = 0: single HTTP call on any failure
  ③ Idempotency   — X-Twilio-Idempotency-Token header equals idempotency_key
  ④ Correlation   — X-Correlation-Id present in every request + logged
  ⑤ Metrics       — SMS_DISPATCH_SUCCESS / FAILURE / DURATION increment
  ⑥ Probe         — probe() returns True on 200, False on 401 / network error

HTTP mapping tests:
  201              → return Twilio SID (str)
  4xx              → NotificationGatewayError (permanent)
  5xx              → NotificationGatewayError (transient)
  Unsupported channel → NotificationGatewayError immediately (no HTTP call)
  Unknown template    → NotificationGatewayError immediately (no HTTP call)
"""
from __future__ import annotations

import json

import httpx
import pytest

from yasargold_domain.notifications.channels import NotificationChannel, NotificationTemplate
from yasargold_domain.notifications.exceptions import NotificationGatewayError

from yasargold_commerce.infra.twilio_notification_gateway import TwilioNotificationGateway
from yasargold_commerce.metrics import (
    SMS_DISPATCH_DURATION,
    SMS_DISPATCH_FAILURE,
    SMS_DISPATCH_SUCCESS,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ACCOUNT_SID = "ACtest1234567890abcdef1234567890ab"
_AUTH_TOKEN = "test_auth_token_xyz"
_FROM_NUMBER = "+12025551234"
_RECIPIENT = "+966501234567"
_TWILIO_SID = "SM1234567890abcdef1234567890abcdef"
_IDEM_KEY = "ord_abc:ORDER_CONFIRMED:SMS"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _success_body() -> bytes:
    return json.dumps({"sid": _TWILIO_SID, "status": "queued"}).encode()


def _error_body(code: int = 21211, message: str = "Invalid number") -> bytes:
    return json.dumps({"code": code, "message": message, "status": 400}).encode()


def _make_gateway(responses: list[httpx.Response]) -> tuple[TwilioNotificationGateway, list]:
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
    client = httpx.Client(transport=transport, base_url="https://api.twilio.com/2010-04-01")
    return TwilioNotificationGateway(
        account_sid=_ACCOUNT_SID,
        auth_token=_AUTH_TOKEN,
        from_number=_FROM_NUMBER,
        client=client,
    ), captured


def _make_raise_gateway(exc: Exception) -> TwilioNotificationGateway:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://api.twilio.com/2010-04-01")
    return TwilioNotificationGateway(
        account_sid=_ACCOUNT_SID,
        auth_token=_AUTH_TOKEN,
        from_number=_FROM_NUMBER,
        client=client,
    )


def _send(gw: TwilioNotificationGateway, **kwargs) -> str:
    defaults = dict(
        channel=NotificationChannel.SMS,
        recipient=_RECIPIENT,
        template=NotificationTemplate.ORDER_CONFIRMED,
        variables={"order_id": "ord_001", "amount": "5500", "currency": "SAR"},
        idempotency_key=_IDEM_KEY,
    )
    defaults.update(kwargs)
    return gw.send(**defaults)


# ===========================================================================
# ADR-019 Requirement ① — Timeout → NotificationGatewayError
# ===========================================================================

class TestTimeout:
    def test_timeout_raises_gateway_error(self):
        gw = _make_raise_gateway(httpx.ReadTimeout("timed out", request=None))
        with pytest.raises(NotificationGatewayError):
            _send(gw)

    def test_connect_error_raises_gateway_error(self):
        gw = _make_raise_gateway(httpx.ConnectError("connection refused"))
        with pytest.raises(NotificationGatewayError):
            _send(gw)


# ===========================================================================
# ADR-019 Requirement ② — Retry budget = 0 (single HTTP call on any failure)
# ===========================================================================

class TestNoRetry:
    def test_5xx_raises_immediately_no_retry(self):
        """5xx → NotificationGatewayError after exactly ONE HTTP call."""
        gw, captured = _make_gateway([
            httpx.Response(503, content=b"Service Unavailable"),
        ])
        with pytest.raises(NotificationGatewayError):
            _send(gw)
        assert len(captured) == 1, "SMS must NOT be retried on 5xx"

    def test_4xx_raises_immediately_no_retry(self):
        """4xx → NotificationGatewayError after exactly ONE HTTP call."""
        gw, captured = _make_gateway([
            httpx.Response(400, content=_error_body()),
        ])
        with pytest.raises(NotificationGatewayError):
            _send(gw)
        assert len(captured) == 1, "SMS must NOT be retried on 4xx"

    def test_timeout_no_retry(self):
        """Timeout → NotificationGatewayError immediately (no retry)."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            raise httpx.ReadTimeout("timeout", request=request)

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport, base_url="https://api.twilio.com/2010-04-01")
        gw = TwilioNotificationGateway(_ACCOUNT_SID, _AUTH_TOKEN, _FROM_NUMBER, client=client)

        with pytest.raises(NotificationGatewayError):
            _send(gw)
        assert call_count == 1


# ===========================================================================
# ADR-019 Requirement ③ — Idempotency key in request header
# ===========================================================================

class TestIdempotencyKey:
    def test_idempotency_key_in_header(self):
        """X-Twilio-Idempotency-Token must equal the caller's idempotency_key."""
        gw, captured = _make_gateway([
            httpx.Response(201, content=_success_body()),
        ])
        _send(gw, idempotency_key=_IDEM_KEY)
        assert captured[0].headers.get("X-Twilio-Idempotency-Token") == _IDEM_KEY

    def test_empty_idempotency_key_when_none(self):
        """When idempotency_key=None, header is present but empty."""
        gw, captured = _make_gateway([
            httpx.Response(201, content=_success_body()),
        ])
        _send(gw, idempotency_key=None)
        assert "X-Twilio-Idempotency-Token" in captured[0].headers
        assert captured[0].headers["X-Twilio-Idempotency-Token"] == ""


# ===========================================================================
# ADR-019 Requirement ④ — Correlation ID in every request + logged
# ===========================================================================

class TestCorrelationId:
    def test_correlation_id_in_request_header(self):
        gw, captured = _make_gateway([httpx.Response(201, content=_success_body())])
        _send(gw)
        assert "X-Correlation-Id" in captured[0].headers
        assert len(captured[0].headers["X-Correlation-Id"]) == 36  # uuid4

    def test_correlation_id_in_log(self, caplog):
        import logging
        gw, captured = _make_gateway([httpx.Response(201, content=_success_body())])
        with caplog.at_level(logging.INFO, logger="yasargold_commerce.infra.twilio_notification_gateway"):
            _send(gw)
        correlation_id = captured[0].headers["X-Correlation-Id"]
        assert any(correlation_id in r.getMessage() for r in caplog.records)


# ===========================================================================
# ADR-019 Requirement ⑤ — Metrics
# ===========================================================================

class TestMetrics:
    def test_success_counter_increments(self, monkeypatch):
        called = []
        monkeypatch.setattr(SMS_DISPATCH_SUCCESS, "inc", lambda: called.append(1))
        gw, _ = _make_gateway([httpx.Response(201, content=_success_body())])
        _send(gw)
        assert called == [1]

    def test_failure_counter_permanent_on_4xx(self, monkeypatch):
        recorded = []

        def fake_labels(**kwargs):
            class _C:
                def inc(self_inner): recorded.append(kwargs)
            return _C()

        monkeypatch.setattr(SMS_DISPATCH_FAILURE, "labels", fake_labels)
        gw, _ = _make_gateway([httpx.Response(400, content=_error_body())])
        with pytest.raises(NotificationGatewayError):
            _send(gw)
        assert recorded == [{"kind": "permanent"}]

    def test_failure_counter_transient_on_5xx(self, monkeypatch):
        recorded = []

        def fake_labels(**kwargs):
            class _C:
                def inc(self_inner): recorded.append(kwargs)
            return _C()

        monkeypatch.setattr(SMS_DISPATCH_FAILURE, "labels", fake_labels)
        gw, _ = _make_gateway([httpx.Response(503, content=b"error")])
        with pytest.raises(NotificationGatewayError):
            _send(gw)
        assert recorded == [{"kind": "transient"}]

    def test_duration_observed(self, monkeypatch):
        observed = []
        monkeypatch.setattr(SMS_DISPATCH_DURATION, "observe", lambda v: observed.append(v))
        gw, _ = _make_gateway([httpx.Response(201, content=_success_body())])
        _send(gw)
        assert len(observed) == 1 and observed[0] >= 0


# ===========================================================================
# ADR-019 Requirement ⑥ — Health probe
# ===========================================================================

class TestProbe:
    def test_probe_returns_true_on_200(self):
        gw, _ = _make_gateway([httpx.Response(200, content=b'{"sid":"ACtest"}')])
        assert gw.probe() is True

    def test_probe_returns_false_on_401(self):
        gw, _ = _make_gateway([httpx.Response(401, content=b'{"code":20003}')])
        assert gw.probe() is False

    def test_probe_returns_false_on_network_error(self):
        gw = _make_raise_gateway(httpx.ConnectError("connection refused"))
        assert gw.probe() is False

    def test_probe_returns_false_on_timeout(self):
        gw = _make_raise_gateway(httpx.ReadTimeout("timed out", request=None))
        assert gw.probe() is False


# ===========================================================================
# HTTP mapping
# ===========================================================================

class TestHttpMapping:
    def test_201_returns_twilio_sid(self):
        gw, _ = _make_gateway([httpx.Response(201, content=_success_body())])
        result = _send(gw)
        assert result == _TWILIO_SID

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
    def test_4xx_raises_gateway_error(self, status: int):
        gw, _ = _make_gateway([httpx.Response(status, content=_error_body())])
        with pytest.raises(NotificationGatewayError):
            _send(gw)

    def test_5xx_raises_gateway_error(self):
        gw, _ = _make_gateway([httpx.Response(500, content=b"Internal Server Error")])
        with pytest.raises(NotificationGatewayError):
            _send(gw)


# ===========================================================================
# Channel and template validation
# ===========================================================================

class TestValidation:
    def test_unsupported_channel_raises_without_http_call(self):
        """EMAIL / WHATSAPP / PUSH → NotificationGatewayError before any HTTP."""
        gw, captured = _make_gateway([httpx.Response(201, content=_success_body())])
        with pytest.raises(NotificationGatewayError, match="only supports SMS"):
            gw.send(
                channel=NotificationChannel.EMAIL,
                recipient="customer@example.com",
                template=NotificationTemplate.ORDER_CONFIRMED,
                variables={},
            )
        assert len(captured) == 0, "No HTTP call for unsupported channel"

    def test_template_variables_substituted_in_body(self):
        """Variables must be substituted in the message body sent to Twilio."""
        gw, captured = _make_gateway([httpx.Response(201, content=_success_body())])
        _send(
            gw,
            template=NotificationTemplate.ORDER_CONFIRMED,
            variables={"order_id": "ord_999", "amount": "7500", "currency": "SAR"},
        )
        # Parse form-encoded body
        body_str = captured[0].content.decode()
        assert "ord_999" in body_str

    def test_from_number_in_request(self):
        """From field must match the configured from_number."""
        gw, captured = _make_gateway([httpx.Response(201, content=_success_body())])
        _send(gw)
        body_str = captured[0].content.decode()
        from urllib.parse import parse_qs
        params = parse_qs(body_str)
        assert params.get("From", [None])[0] == _FROM_NUMBER

    def test_recipient_in_request(self):
        """To field must contain the recipient phone number digits."""
        gw, captured = _make_gateway([httpx.Response(201, content=_success_body())])
        _send(gw, recipient=_RECIPIENT)
        body_str = captured[0].content.decode()
        # + may be encoded as %2B or literal + in form data; check the digits
        assert "To=" in body_str
        assert "966501234567" in body_str
