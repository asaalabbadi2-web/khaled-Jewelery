"""AramexCarrierGateway — ShippingGateway adapter for Aramex.

ADR-019 requirements:
  ① Timeout       — every HTTP call uses DEFAULT_TIMEOUT via build_http_client
  ② Retry         — 5xx and 429 retried (3 attempts, exponential backoff 0.5→1.0→2.0s)
                    400/401/403/404/409/422 → ShipmentGatewayError immediately (no retry)
  ③ Idempotency   — Idempotency-Key header on all write operations
                    create: caller-supplied idempotency_key (f"{order_id}:SHIPMENT")
                    void:   f"void:{tracking_number}" — derived, stable across retries
  ④ Correlation   — X-Correlation-Id: uuid4 per call, logged for incident tracing
  ⑤ Metrics       — CARRIER_SHIPMENT_* and CARRIER_VOID_* per call
  ⑥ Probe         — probe() returns True on any HTTP response, False on network error

HTTP status → domain exception:
  200/201          → success (return tracking_number or None)
  204              → success for void (no body)
  400/401/403/404/409/422 → ShipmentGatewayError (permanent — no retry)
  429/5xx          → retry; ShipmentGatewayError after _MAX_RETRIES exhausted
  network/timeout  → retry; ShipmentGatewayError after _MAX_RETRIES exhausted

Availability vs capability (ADR-019 §7):
  probe() answers: can we reach the Aramex API?
  create_shipment()/void_shipment() answers: did the carrier accept this operation?
  A 409 from Aramex is a business rejection, not an infrastructure failure.

Aramex REST API v2:
  Base URL: https://ws.aramex.net/ShippingAPI.V2
  Auth:     Bearer token in Authorization header (injected at construction)
  Create:   POST /Shipping/CreateShipments
            Body: {"order_id", "declared_value", "currency"}
            Returns: {"tracking_number": "AWB-...", "shipment_id": "..."}
  Void:     POST /Shipping/CancelShipment
            Body: {"tracking_number", "reason"}
            Returns: 200/204
  Probe:    GET  /Shipping/ping
"""
from __future__ import annotations

import logging
import time
import uuid
from decimal import Decimal

import httpx

from yasargold_commerce.infra.http_client import (
    _log_request,
    _log_response,
    build_http_client,
)
from yasargold_commerce.metrics import (
    CARRIER_SHIPMENT_DURATION,
    CARRIER_SHIPMENT_FAILURE,
    CARRIER_SHIPMENT_SUCCESS,
    CARRIER_VOID_DURATION,
    CARRIER_VOID_FAILURE,
    CARRIER_VOID_SUCCESS,
)
from yasargold_domain.shared.identifiers import OrderId
from yasargold_domain.shipping.exceptions import ShipmentGatewayError

log = logging.getLogger(__name__)

_ARAMEX_BASE = "https://ws.aramex.net/ShippingAPI.V2"
_MAX_RETRIES = 3
_BACKOFF_BASE = 0.5  # seconds: 0.5 → 1.0 → 2.0

# 4xx codes that indicate a permanent failure — the carrier has definitively rejected the request
_PERMANENT_CODES = frozenset({400, 401, 403, 404, 409, 422})


class AramexCarrierGateway:
    """Implements ShippingGateway by calling the Aramex Shipping API v2.

    All failures raise ShipmentGatewayError — the only exception type
    the domain sees from the carrier boundary. No HTTPException raised here.

    Args:
        api_key: Aramex API key passed as Bearer token.
        client:  Optional pre-configured httpx.Client for tests — pass a client
                 with MockTransport to avoid any network calls.
    """

    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._client = client or build_http_client(
            _ARAMEX_BASE,
            default_headers={"Authorization": f"Bearer {api_key}"},
        )

    def create_shipment(
        self,
        order_id: OrderId,
        carrier_id: str,
        declared_value: Decimal,
        idempotency_key: str,
    ) -> str:
        """Register a shipment with Aramex and return the AWB tracking number.

        Retries on transient failures (429, 5xx, network). Permanent 4xx errors
        raise immediately without retry.

        Raises:
            ShipmentGatewayError: any carrier failure — caller records FAILED status.
        """
        correlation_id = str(uuid.uuid4())
        url = "/Shipping/CreateShipments"
        payload = {
            "order_id": str(order_id),
            "declared_value": str(declared_value),
            "currency": "SAR",
        }

        log.info(
            "aramex_carrier: create_shipment order_id=%s declared_value=%s correlation_id=%s",
            order_id,
            declared_value,
            correlation_id,
        )

        _op_start = time.monotonic()
        last_exc: Exception | None = None

        for attempt in range(1, _MAX_RETRIES + 1):
            req_start = _log_request("POST", f"{_ARAMEX_BASE}{url}")
            try:
                response = self._client.post(
                    url,
                    json=payload,
                    headers={
                        "Idempotency-Key": idempotency_key,
                        "X-Correlation-Id": correlation_id,
                    },
                )
                _log_response("POST", f"{_ARAMEX_BASE}{url}", response.status_code, req_start)
            except httpx.TimeoutException as exc:
                log.warning(
                    "aramex_carrier: create timeout attempt=%d/%d correlation_id=%s",
                    attempt, _MAX_RETRIES, correlation_id,
                )
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    time.sleep(_BACKOFF_BASE * (2 ** (attempt - 1)))
                continue
            except (httpx.ConnectError, httpx.NetworkError) as exc:
                log.warning(
                    "aramex_carrier: create network error attempt=%d/%d error=%s correlation_id=%s",
                    attempt, _MAX_RETRIES, exc, correlation_id,
                )
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    time.sleep(_BACKOFF_BASE * (2 ** (attempt - 1)))
                continue

            status = response.status_code

            if status in (200, 201):
                CARRIER_SHIPMENT_DURATION.observe(time.monotonic() - _op_start)
                CARRIER_SHIPMENT_SUCCESS.inc()
                tracking_number = response.json()["tracking_number"]
                log.info(
                    "aramex_carrier: shipment created order_id=%s tracking=%s correlation_id=%s",
                    order_id, tracking_number, correlation_id,
                )
                return tracking_number

            if status in _PERMANENT_CODES:
                CARRIER_SHIPMENT_DURATION.observe(time.monotonic() - _op_start)
                CARRIER_SHIPMENT_FAILURE.labels(kind="permanent").inc()
                raise ShipmentGatewayError(
                    carrier_id,
                    f"aramex {status} for order_id={order_id}: {response.text[:200]}",
                )

            # 429 or 5xx — transient, retry within adapter
            log.warning(
                "aramex_carrier: create %d attempt=%d/%d correlation_id=%s",
                status, attempt, _MAX_RETRIES, correlation_id,
            )
            last_exc = ShipmentGatewayError(
                carrier_id, f"aramex {status}: {response.text[:100]}"
            )
            if attempt < _MAX_RETRIES:
                time.sleep(_BACKOFF_BASE * (2 ** (attempt - 1)))

        CARRIER_SHIPMENT_DURATION.observe(time.monotonic() - _op_start)
        CARRIER_SHIPMENT_FAILURE.labels(kind="transient").inc()
        raise ShipmentGatewayError(
            carrier_id,
            f"aramex create_shipment failed after {_MAX_RETRIES} attempts for order_id={order_id}",
        ) from last_exc

    def void_shipment(self, carrier_id: str, tracking_number: str) -> None:
        """Cancel a registered Aramex shipment within the void_window.

        The idempotency key is derived from the tracking number — stable and safe to retry.

        Raises:
            ShipmentGatewayError: any carrier failure — caller records FAILED status.
        """
        idempotency_key = f"void:{tracking_number}"
        correlation_id = str(uuid.uuid4())
        url = "/Shipping/CancelShipment"
        payload = {
            "tracking_number": tracking_number,
            "reason": "customer_request",
        }

        log.info(
            "aramex_carrier: void_shipment tracking=%s correlation_id=%s",
            tracking_number, correlation_id,
        )

        _op_start = time.monotonic()
        last_exc: Exception | None = None

        for attempt in range(1, _MAX_RETRIES + 1):
            req_start = _log_request("POST", f"{_ARAMEX_BASE}{url}")
            try:
                response = self._client.post(
                    url,
                    json=payload,
                    headers={
                        "Idempotency-Key": idempotency_key,
                        "X-Correlation-Id": correlation_id,
                    },
                )
                _log_response("POST", f"{_ARAMEX_BASE}{url}", response.status_code, req_start)
            except httpx.TimeoutException as exc:
                log.warning(
                    "aramex_carrier: void timeout attempt=%d/%d correlation_id=%s",
                    attempt, _MAX_RETRIES, correlation_id,
                )
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    time.sleep(_BACKOFF_BASE * (2 ** (attempt - 1)))
                continue
            except (httpx.ConnectError, httpx.NetworkError) as exc:
                log.warning(
                    "aramex_carrier: void network error attempt=%d/%d error=%s correlation_id=%s",
                    attempt, _MAX_RETRIES, exc, correlation_id,
                )
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    time.sleep(_BACKOFF_BASE * (2 ** (attempt - 1)))
                continue

            status = response.status_code

            if status in (200, 204):
                CARRIER_VOID_DURATION.observe(time.monotonic() - _op_start)
                CARRIER_VOID_SUCCESS.inc()
                log.info(
                    "aramex_carrier: shipment voided tracking=%s correlation_id=%s",
                    tracking_number, correlation_id,
                )
                return

            if status in _PERMANENT_CODES:
                CARRIER_VOID_DURATION.observe(time.monotonic() - _op_start)
                CARRIER_VOID_FAILURE.labels(kind="permanent").inc()
                raise ShipmentGatewayError(
                    carrier_id,
                    f"aramex {status} voiding {tracking_number}: {response.text[:200]}",
                )

            # 429 or 5xx — transient, retry within adapter
            log.warning(
                "aramex_carrier: void %d attempt=%d/%d correlation_id=%s",
                status, attempt, _MAX_RETRIES, correlation_id,
            )
            last_exc = ShipmentGatewayError(
                carrier_id, f"aramex {status}: {response.text[:100]}"
            )
            if attempt < _MAX_RETRIES:
                time.sleep(_BACKOFF_BASE * (2 ** (attempt - 1)))

        CARRIER_VOID_DURATION.observe(time.monotonic() - _op_start)
        CARRIER_VOID_FAILURE.labels(kind="transient").inc()
        raise ShipmentGatewayError(
            carrier_id,
            f"aramex void_shipment failed after {_MAX_RETRIES} attempts for tracking={tracking_number}",
        ) from last_exc

    def probe(self) -> bool:
        """Return True if the Aramex API is reachable.

        Any HTTP response (including 401/403) means the network path is up.
        Returns False only on network or timeout errors.
        """
        try:
            self._client.get("/Shipping/ping")
            return True
        except (httpx.ConnectError, httpx.NetworkError, httpx.TimeoutException):
            return False
