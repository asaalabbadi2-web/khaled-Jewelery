"""MoyasarRefundGateway — RefundGateway adapter for Moyasar.

ADR-019 requirements:
  ① Timeout       — every HTTP call uses DEFAULT_TIMEOUT via build_http_client
  ② Retry         — 5xx and 429 retried (3 attempts, exponential backoff 0.5→1.0→2.0s)
                    202 → RefundTransientError immediately (RefundWorker retries, not adapter)
                    400/401/404/409 → RefundPermanentError immediately (no retry ever)
  ③ Idempotency   — Idempotency-Key: {intent.id} on every POST (enables safe retry)
  ④ Correlation   — X-Correlation-Id: uuid4 per call, logged at INFO for incident tracing
  ⑤ Metrics       — PAYMENT_REFUND_SUCCESS / FAILURE / DURATION recorded at every exit
  ⑥ Probe         — probe() returns True on any HTTP response, False on network error

HTTP status → domain exception:
  200                → success (return None)
  202 (pending)      → RefundTransientError — RefundWorker retries later
  400/401/404/409    → RefundPermanentError — manual intervention required
  429 / 5xx          → RefundTransientError — retried within adapter
  timeout / network  → RefundTransientError — retried within adapter
"""
from __future__ import annotations

import logging
import time
import uuid

import httpx

from yasargold_commerce.infra.http_client import (
    DEFAULT_TIMEOUT,
    _log_request,
    _log_response,
    build_http_client,
)
from yasargold_commerce.metrics import (
    PAYMENT_REFUND_DURATION,
    PAYMENT_REFUND_FAILURE,
    PAYMENT_REFUND_SUCCESS,
)
from yasargold_domain.payment.intent import PaymentIntent
from yasargold_domain.payment.refund_gateway import RefundPermanentError, RefundTransientError

log = logging.getLogger(__name__)

_MOYASAR_BASE = "https://api.moyasar.com/v1"
_MAX_RETRIES = 3
_BACKOFF_BASE = 0.5  # seconds: 0.5 → 1.0 → 2.0

# 4xx status codes that indicate a permanent failure — never retry
_PERMANENT_CODES = frozenset({400, 401, 404, 409})


class MoyasarRefundGateway:
    """Implements RefundGateway by calling Moyasar POST /v1/refunds/{provider_ref}.

    No business rules live here. No raise HTTPException. Every exit raises a
    domain exception (RefundTransientError / RefundPermanentError) or returns None.

    Args:
        api_key: Moyasar publishable key (HTTP Basic auth, empty password).
        client:  Optional pre-configured httpx.Client for tests — pass a client
                 with MockTransport to avoid any network calls.
    """

    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._client = client or build_http_client(_MOYASAR_BASE)

    def refund(self, intent: PaymentIntent) -> None:
        """Issue a full refund for intent.provider_reference via Moyasar.

        Raises:
            RefundTransientError: transient failure — RefundWorker will retry later.
            RefundPermanentError: permanent failure — manual intervention required.
        """
        idempotency_key = str(intent.id)
        correlation_id = str(uuid.uuid4())
        url = f"/refunds/{intent.provider_reference}"
        payload = {
            "amount": int(intent.amount * 100),  # SAR → halala (Moyasar's smallest unit)
            "reason": "requested_by_customer",
        }

        log.info(
            "moyasar_refund: initiating intent=%s provider_ref=%s amount=%s correlation_id=%s",
            intent.id,
            intent.provider_reference,
            intent.amount,
            correlation_id,
        )

        _op_start = time.monotonic()
        last_exc: Exception | None = None

        for attempt in range(1, _MAX_RETRIES + 1):
            req_start = _log_request("POST", f"{_MOYASAR_BASE}{url}")
            try:
                response = self._client.post(
                    url,
                    json=payload,
                    auth=(self._api_key, ""),
                    headers={
                        "Idempotency-Key": idempotency_key,
                        "X-Correlation-Id": correlation_id,
                    },
                )
                _log_response("POST", f"{_MOYASAR_BASE}{url}", response.status_code, req_start)
            except httpx.TimeoutException as exc:
                log.warning(
                    "moyasar_refund: timeout attempt=%d/%d correlation_id=%s",
                    attempt, _MAX_RETRIES, correlation_id,
                )
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    time.sleep(_BACKOFF_BASE * (2 ** (attempt - 1)))
                continue
            except (httpx.ConnectError, httpx.NetworkError) as exc:
                log.warning(
                    "moyasar_refund: network error attempt=%d/%d error=%s correlation_id=%s",
                    attempt, _MAX_RETRIES, exc, correlation_id,
                )
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    time.sleep(_BACKOFF_BASE * (2 ** (attempt - 1)))
                continue

            status = response.status_code

            if status == 200:
                PAYMENT_REFUND_DURATION.observe(time.monotonic() - _op_start)
                PAYMENT_REFUND_SUCCESS.inc()
                log.info(
                    "moyasar_refund: success intent=%s correlation_id=%s",
                    intent.id, correlation_id,
                )
                return

            if status in _PERMANENT_CODES:
                PAYMENT_REFUND_DURATION.observe(time.monotonic() - _op_start)
                PAYMENT_REFUND_FAILURE.labels(kind="permanent").inc()
                raise RefundPermanentError(
                    f"moyasar {status} for intent={intent.id}: {response.text[:200]}"
                )

            if status == 202:
                # Moyasar accepted the request but refund is still processing.
                # Not retried in the adapter — RefundWorker picks it up next tick.
                PAYMENT_REFUND_DURATION.observe(time.monotonic() - _op_start)
                PAYMENT_REFUND_FAILURE.labels(kind="transient").inc()
                raise RefundTransientError(
                    f"moyasar 202 (pending) for intent={intent.id} — RefundWorker will retry"
                )

            # 429 or 5xx — transient, retry within adapter
            log.warning(
                "moyasar_refund: %d attempt=%d/%d correlation_id=%s",
                status, attempt, _MAX_RETRIES, correlation_id,
            )
            last_exc = RefundTransientError(f"moyasar {status}: {response.text[:100]}")
            if attempt < _MAX_RETRIES:
                time.sleep(_BACKOFF_BASE * (2 ** (attempt - 1)))

        # All retries exhausted
        PAYMENT_REFUND_DURATION.observe(time.monotonic() - _op_start)
        PAYMENT_REFUND_FAILURE.labels(kind="transient").inc()
        raise RefundTransientError(
            f"moyasar refund failed after {_MAX_RETRIES} attempts for intent={intent.id}"
        ) from last_exc

    def probe(self) -> bool:
        """Return True if Moyasar API is reachable without executing a business transaction.

        Hits a non-existent refund ID — Moyasar returns 404, which confirms the API
        is up and accepting requests. Network or connection failure returns False.
        """
        try:
            self._client.get("/refunds/connectivity-probe", auth=(self._api_key, ""))
            return True  # Any HTTP response (including 404) means the API is up
        except (httpx.ConnectError, httpx.NetworkError, httpx.TimeoutException):
            return False
