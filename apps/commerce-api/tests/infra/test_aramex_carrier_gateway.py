"""Unit tests for AramexCarrierGateway — zero network calls.

ADR-019 requirements verified for both create_shipment() and void_shipment():
  ① Timeout       — httpx.TimeoutException → ShipmentGatewayError
  ② Retry         — 3 attempts on 5xx/429/network; no retry on permanent 4xx
  ③ Idempotency   — Idempotency-Key header on every write; stable across retries
  ④ Correlation   — X-Correlation-Id present in every request + logged at INFO
  ⑤ Metrics       — CARRIER_SHIPMENT_* / CARRIER_VOID_* counters increment
  ⑥ Probe         — probe() True on any HTTP response, False on network/timeout

HTTP mapping:
  200/201  (create) → tracking_number string
  200/204  (void)   → None
  4xx permanent     → ShipmentGatewayError immediately (no retry)
  5xx / 429         → ShipmentGatewayError after 3 attempts
  timeout / network → ShipmentGatewayError after 3 attempts
"""
from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest

from yasargold_domain.shared.identifiers import OrderId
from yasargold_domain.shipping.exceptions import ShipmentGatewayError

from yasargold_commerce.infra.aramex_carrier_gateway import AramexCarrierGateway
from yasargold_commerce.metrics import (
    CARRIER_SHIPMENT_DURATION,
    CARRIER_SHIPMENT_FAILURE,
    CARRIER_SHIPMENT_SUCCESS,
    CARRIER_VOID_DURATION,
    CARRIER_VOID_FAILURE,
    CARRIER_VOID_SUCCESS,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_API_KEY = "aramex_test_key_abc123"
_ORDER_ID = OrderId("ord_aramex_test_001")
_CARRIER_ID = "aramex"
_DECLARED_VALUE = Decimal("5500.00")
_TRACKING_NUMBER = "AWB-123456789"
_IDEM_KEY = "ord_aramex_test_001:SHIPMENT"

_SLEEP_PATH = "yasargold_commerce.infra.aramex_carrier_gateway.time.sleep"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_body(tracking: str = _TRACKING_NUMBER) -> bytes:
    return json.dumps({"tracking_number": tracking, "shipment_id": "SHP-001"}).encode()


def _error_body(code: str = "VALIDATION_ERROR", msg: str = "Invalid input") -> bytes:
    return json.dumps({"code": code, "message": msg}).encode()


def _make_gateway(
    responses: list[httpx.Response],
) -> tuple[AramexCarrierGateway, list[httpx.Request]]:
    """Return (gateway, captured_requests). Responses are consumed in order."""
    captured: list[httpx.Request] = []
    idx = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal idx
        captured.append(request)
        resp = responses[idx]
        idx = min(idx + 1, len(responses) - 1)
        return resp

    transport = httpx.MockTransport(handler)
    client = httpx.Client(
        transport=transport,
        base_url="https://ws.aramex.net/ShippingAPI.V2",
    )
    return AramexCarrierGateway(api_key=_API_KEY, client=client), captured


def _make_raise_gateway(exc: Exception) -> AramexCarrierGateway:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    transport = httpx.MockTransport(handler)
    client = httpx.Client(
        transport=transport,
        base_url="https://ws.aramex.net/ShippingAPI.V2",
    )
    return AramexCarrierGateway(api_key=_API_KEY, client=client)


def _create(gw: AramexCarrierGateway, **kwargs) -> str:
    defaults = dict(
        order_id=_ORDER_ID,
        carrier_id=_CARRIER_ID,
        declared_value=_DECLARED_VALUE,
        idempotency_key=_IDEM_KEY,
    )
    defaults.update(kwargs)
    return gw.create_shipment(**defaults)


def _void(gw: AramexCarrierGateway, **kwargs) -> None:
    defaults = dict(carrier_id=_CARRIER_ID, tracking_number=_TRACKING_NUMBER)
    defaults.update(kwargs)
    gw.void_shipment(**defaults)


# ===========================================================================
# create_shipment() — ADR-019 Requirement ① Timeout
# ===========================================================================


class TestCreateTimeout:
    def test_read_timeout_raises_gateway_error(self, monkeypatch):
        monkeypatch.setattr(_SLEEP_PATH, lambda _: None)
        gw = _make_raise_gateway(httpx.ReadTimeout("timed out", request=None))
        with pytest.raises(ShipmentGatewayError):
            _create(gw)

    def test_connect_error_raises_gateway_error(self, monkeypatch):
        monkeypatch.setattr(_SLEEP_PATH, lambda _: None)
        gw = _make_raise_gateway(httpx.ConnectError("connection refused"))
        with pytest.raises(ShipmentGatewayError):
            _create(gw)


# ===========================================================================
# create_shipment() — ADR-019 Requirement ② Retry
# ===========================================================================


class TestCreateRetry:
    def test_retries_3_times_on_5xx(self, monkeypatch):
        monkeypatch.setattr(_SLEEP_PATH, lambda _: None)
        gw, captured = _make_gateway([
            httpx.Response(503, content=b"Service Unavailable"),
            httpx.Response(503, content=b"Service Unavailable"),
            httpx.Response(503, content=b"Service Unavailable"),
        ])
        with pytest.raises(ShipmentGatewayError):
            _create(gw)
        assert len(captured) == 3

    def test_success_on_3rd_attempt(self, monkeypatch):
        monkeypatch.setattr(_SLEEP_PATH, lambda _: None)
        gw, captured = _make_gateway([
            httpx.Response(503, content=b"error"),
            httpx.Response(429, content=b"Too Many Requests"),
            httpx.Response(200, content=_create_body()),
        ])
        result = _create(gw)
        assert result == _TRACKING_NUMBER
        assert len(captured) == 3

    def test_no_retry_on_permanent_4xx(self, monkeypatch):
        monkeypatch.setattr(_SLEEP_PATH, lambda _: None)
        gw, captured = _make_gateway([
            httpx.Response(400, content=_error_body()),
            httpx.Response(200, content=_create_body()),  # must never be reached
        ])
        with pytest.raises(ShipmentGatewayError):
            _create(gw)
        assert len(captured) == 1, "permanent 4xx must not trigger retry"

    def test_retries_on_429(self, monkeypatch):
        monkeypatch.setattr(_SLEEP_PATH, lambda _: None)
        gw, captured = _make_gateway([
            httpx.Response(429, content=b"rate limited"),
            httpx.Response(200, content=_create_body()),
        ])
        result = _create(gw)
        assert result == _TRACKING_NUMBER
        assert len(captured) == 2


# ===========================================================================
# create_shipment() — ADR-019 Requirement ③ Idempotency
# ===========================================================================


class TestCreateIdempotency:
    def test_idempotency_key_in_header(self):
        gw, captured = _make_gateway([httpx.Response(200, content=_create_body())])
        _create(gw, idempotency_key=_IDEM_KEY)
        assert captured[0].headers.get("Idempotency-Key") == _IDEM_KEY

    def test_idempotency_key_stable_across_retries(self, monkeypatch):
        monkeypatch.setattr(_SLEEP_PATH, lambda _: None)
        gw, captured = _make_gateway([
            httpx.Response(503, content=b"error"),
            httpx.Response(200, content=_create_body()),
        ])
        _create(gw, idempotency_key=_IDEM_KEY)
        assert all(r.headers.get("Idempotency-Key") == _IDEM_KEY for r in captured)


# ===========================================================================
# create_shipment() — ADR-019 Requirement ④ Correlation ID
# ===========================================================================


class TestCreateCorrelation:
    def test_correlation_id_present_in_request(self):
        gw, captured = _make_gateway([httpx.Response(200, content=_create_body())])
        _create(gw)
        assert "X-Correlation-Id" in captured[0].headers
        assert len(captured[0].headers["X-Correlation-Id"]) == 36  # uuid4

    def test_correlation_id_in_log(self, caplog):
        import logging

        gw, captured = _make_gateway([httpx.Response(200, content=_create_body())])
        with caplog.at_level(
            logging.INFO, logger="yasargold_commerce.infra.aramex_carrier_gateway"
        ):
            _create(gw)
        correlation_id = captured[0].headers["X-Correlation-Id"]
        assert any(correlation_id in r.getMessage() for r in caplog.records)


# ===========================================================================
# create_shipment() — ADR-019 Requirement ⑤ Metrics
# ===========================================================================


class TestCreateMetrics:
    def test_success_counter_increments(self, monkeypatch):
        called = []
        monkeypatch.setattr(CARRIER_SHIPMENT_SUCCESS, "inc", lambda: called.append(1))
        gw, _ = _make_gateway([httpx.Response(200, content=_create_body())])
        _create(gw)
        assert called == [1]

    def test_failure_counter_permanent_on_4xx(self, monkeypatch):
        recorded = []

        def fake_labels(**kwargs):
            class _C:
                def inc(self_inner):
                    recorded.append(kwargs)

            return _C()

        monkeypatch.setattr(CARRIER_SHIPMENT_FAILURE, "labels", fake_labels)
        gw, _ = _make_gateway([httpx.Response(400, content=_error_body())])
        with pytest.raises(ShipmentGatewayError):
            _create(gw)
        assert recorded == [{"kind": "permanent"}]

    def test_failure_counter_transient_after_5xx_exhaustion(self, monkeypatch):
        monkeypatch.setattr(_SLEEP_PATH, lambda _: None)
        recorded = []

        def fake_labels(**kwargs):
            class _C:
                def inc(self_inner):
                    recorded.append(kwargs)

            return _C()

        monkeypatch.setattr(CARRIER_SHIPMENT_FAILURE, "labels", fake_labels)
        gw, _ = _make_gateway([httpx.Response(503, content=b"error")] * 3)
        with pytest.raises(ShipmentGatewayError):
            _create(gw)
        assert recorded == [{"kind": "transient"}]

    def test_duration_observed_on_success(self, monkeypatch):
        observed = []
        monkeypatch.setattr(CARRIER_SHIPMENT_DURATION, "observe", lambda v: observed.append(v))
        gw, _ = _make_gateway([httpx.Response(200, content=_create_body())])
        _create(gw)
        assert len(observed) == 1 and observed[0] >= 0


# ===========================================================================
# void_shipment() — ADR-019 Requirement ① Timeout
# ===========================================================================


class TestVoidTimeout:
    def test_timeout_raises_gateway_error(self, monkeypatch):
        monkeypatch.setattr(_SLEEP_PATH, lambda _: None)
        gw = _make_raise_gateway(httpx.ReadTimeout("timed out", request=None))
        with pytest.raises(ShipmentGatewayError):
            _void(gw)


# ===========================================================================
# void_shipment() — ADR-019 Requirement ② Retry
# ===========================================================================


class TestVoidRetry:
    def test_retries_3_times_on_5xx(self, monkeypatch):
        monkeypatch.setattr(_SLEEP_PATH, lambda _: None)
        gw, captured = _make_gateway([
            httpx.Response(503, content=b"error"),
            httpx.Response(503, content=b"error"),
            httpx.Response(503, content=b"error"),
        ])
        with pytest.raises(ShipmentGatewayError):
            _void(gw)
        assert len(captured) == 3

    def test_no_retry_on_permanent_4xx(self):
        gw, captured = _make_gateway([
            httpx.Response(409, content=_error_body("ALREADY_VOIDED", "Shipment already cancelled")),
            httpx.Response(200, content=b"{}"),
        ])
        with pytest.raises(ShipmentGatewayError):
            _void(gw)
        assert len(captured) == 1

    def test_success_after_transient_5xx(self, monkeypatch):
        monkeypatch.setattr(_SLEEP_PATH, lambda _: None)
        gw, captured = _make_gateway([
            httpx.Response(503, content=b"error"),
            httpx.Response(200, content=b'{"status": "cancelled"}'),
        ])
        _void(gw)
        assert len(captured) == 2


# ===========================================================================
# void_shipment() — ADR-019 Requirement ③ Idempotency
# ===========================================================================


class TestVoidIdempotency:
    def test_idempotency_key_derived_from_tracking_number(self):
        gw, captured = _make_gateway([httpx.Response(200, content=b"{}")])
        _void(gw, tracking_number=_TRACKING_NUMBER)
        expected_key = f"void:{_TRACKING_NUMBER}"
        assert captured[0].headers.get("Idempotency-Key") == expected_key


# ===========================================================================
# void_shipment() — ADR-019 Requirement ④ Correlation ID
# ===========================================================================


class TestVoidCorrelation:
    def test_correlation_id_present_in_request(self):
        gw, captured = _make_gateway([httpx.Response(200, content=b"{}")])
        _void(gw)
        assert "X-Correlation-Id" in captured[0].headers
        assert len(captured[0].headers["X-Correlation-Id"]) == 36


# ===========================================================================
# void_shipment() — ADR-019 Requirement ⑤ Metrics
# ===========================================================================


class TestVoidMetrics:
    def test_success_counter_increments(self, monkeypatch):
        called = []
        monkeypatch.setattr(CARRIER_VOID_SUCCESS, "inc", lambda: called.append(1))
        gw, _ = _make_gateway([httpx.Response(200, content=b"{}")])
        _void(gw)
        assert called == [1]

    def test_failure_counter_permanent_on_4xx(self, monkeypatch):
        recorded = []

        def fake_labels(**kwargs):
            class _C:
                def inc(self_inner):
                    recorded.append(kwargs)

            return _C()

        monkeypatch.setattr(CARRIER_VOID_FAILURE, "labels", fake_labels)
        gw, _ = _make_gateway([httpx.Response(404, content=_error_body())])
        with pytest.raises(ShipmentGatewayError):
            _void(gw)
        assert recorded == [{"kind": "permanent"}]

    def test_duration_observed_on_success(self, monkeypatch):
        observed = []
        monkeypatch.setattr(CARRIER_VOID_DURATION, "observe", lambda v: observed.append(v))
        gw, _ = _make_gateway([httpx.Response(200, content=b"{}")])
        _void(gw)
        assert len(observed) == 1 and observed[0] >= 0


# ===========================================================================
# ADR-019 Requirement ⑥ — Health probe (shared availability signal)
# ===========================================================================


class TestProbe:
    def test_probe_returns_true_on_200(self):
        gw, _ = _make_gateway([httpx.Response(200, content=b'{"status": "ok"}')])
        assert gw.probe() is True

    def test_probe_returns_true_on_any_http_response(self):
        """Probe is transport-only: even 401 confirms the API is reachable."""
        gw, _ = _make_gateway([httpx.Response(401, content=b'{"error": "unauthorized"}')])
        assert gw.probe() is True

    def test_probe_returns_false_on_network_error(self):
        gw = _make_raise_gateway(httpx.ConnectError("connection refused"))
        assert gw.probe() is False

    def test_probe_returns_false_on_timeout(self):
        gw = _make_raise_gateway(httpx.ReadTimeout("timed out", request=None))
        assert gw.probe() is False


# ===========================================================================
# HTTP mapping — create_shipment()
# ===========================================================================


class TestCreateHttpMapping:
    def test_200_returns_tracking_number(self):
        gw, _ = _make_gateway([httpx.Response(200, content=_create_body(_TRACKING_NUMBER))])
        assert _create(gw) == _TRACKING_NUMBER

    def test_201_returns_tracking_number(self):
        gw, _ = _make_gateway([httpx.Response(201, content=_create_body("AWB-999"))])
        assert _create(gw) == "AWB-999"

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422])
    def test_permanent_4xx_raises_immediately(self, status: int, monkeypatch):
        monkeypatch.setattr(_SLEEP_PATH, lambda _: None)
        gw, captured = _make_gateway([httpx.Response(status, content=_error_body())])
        with pytest.raises(ShipmentGatewayError):
            _create(gw)
        assert len(captured) == 1

    def test_5xx_raises_after_all_retries_exhausted(self, monkeypatch):
        monkeypatch.setattr(_SLEEP_PATH, lambda _: None)
        gw, _ = _make_gateway([httpx.Response(500, content=b"Internal Server Error")] * 3)
        with pytest.raises(ShipmentGatewayError):
            _create(gw)


# ===========================================================================
# HTTP mapping — void_shipment()
# ===========================================================================


class TestVoidHttpMapping:
    def test_200_returns_none(self):
        gw, _ = _make_gateway([httpx.Response(200, content=b'{"status": "cancelled"}')])
        assert _void(gw) is None

    def test_204_returns_none(self):
        gw, _ = _make_gateway([httpx.Response(204, content=b"")])
        assert _void(gw) is None

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422])
    def test_permanent_4xx_raises_immediately(self, status: int):
        gw, captured = _make_gateway([httpx.Response(status, content=_error_body())])
        with pytest.raises(ShipmentGatewayError):
            _void(gw)
        assert len(captured) == 1
