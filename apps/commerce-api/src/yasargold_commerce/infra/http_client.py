"""Shared HTTP client for all external provider adapters.

All outbound HTTP calls (Moyasar, gold price feeds, shipping, SMS) use this
module. Zero configuration duplication across adapters.

Responsibilities:
  - Default timeouts (connect=5 s, read=15 s, total=30 s)
  - Retry on transient errors (5xx, network failure) with exponential backoff
  - 4xx errors are NOT retried — they indicate caller error, not server error
  - Connection pooling via httpx.Client (one client per provider instance)
  - Structured logging of request method/URL, status, and elapsed time
  - TLS verification always enabled — never pass verify=False

What this file must NOT do:
  - Know about any specific provider (no Moyasar imports here)
  - Know about any domain concept (no PaymentIntent here)
  - Parse response bodies — callers do that

ADR-009: External Providers Are Adapters.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Timeout defaults
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT = httpx.Timeout(
    connect=5.0,
    read=15.0,
    write=10.0,
    pool=5.0,
)

# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 0.5  # seconds: 0.5 → 1.0 → 2.0


def _is_retryable(exc: Exception) -> bool:
    """True for transient network errors and 5xx responses."""
    if isinstance(exc, (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError)):
        return True
    if isinstance(exc, _ProviderHttpError) and exc.status_code >= 500:
        return True
    return False


class _ProviderHttpError(Exception):
    """Raised when the provider returns a non-2xx HTTP response."""

    def __init__(self, status_code: int, body: str, provider: str) -> None:
        self.status_code = status_code
        self.body = body
        self.provider = provider
        super().__init__(f"{provider} HTTP {status_code}: {body[:200]}")


# ---------------------------------------------------------------------------
# Logging middleware
# ---------------------------------------------------------------------------

def _log_request(method: str, url: str) -> float:
    logger.debug("→ %s %s", method.upper(), url)
    return time.monotonic()


def _log_response(method: str, url: str, status: int, start: float) -> None:
    elapsed_ms = (time.monotonic() - start) * 1000
    level = logging.WARNING if status >= 400 else logging.DEBUG
    logger.log(level, "← %s %s  status=%d  elapsed=%.1fms", method.upper(), url, status, elapsed_ms)


# ---------------------------------------------------------------------------
# Retry wrapper
# ---------------------------------------------------------------------------

def _with_retry(fn: Any, provider: str, *args: Any, **kwargs: Any) -> httpx.Response:
    """Call fn(*args, **kwargs) with exponential backoff for transient errors.

    Raises _ProviderHttpError for non-2xx responses after all retries.
    Raises the last exception for network-level failures.
    """
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response: httpx.Response = fn(*args, **kwargs)
            if response.status_code >= 400:
                exc = _ProviderHttpError(response.status_code, response.text, provider)
                if response.status_code < 500:
                    raise exc  # 4xx: never retry
                last_exc = exc
            else:
                return response
        except _ProviderHttpError:
            raise
        except Exception as exc:
            last_exc = exc

        if attempt < _MAX_RETRIES:
            sleep_time = _RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
            logger.warning(
                "%s: attempt %d/%d failed (%s). Retrying in %.1fs.",
                provider, attempt, _MAX_RETRIES, last_exc, sleep_time,
            )
            time.sleep(sleep_time)

    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

def build_http_client(
    base_url: str = "",
    *,
    timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    default_headers: dict[str, str] | None = None,
) -> httpx.Client:
    """Return a configured httpx.Client with connection pooling enabled.

    Args:
        base_url:        Optional base URL prefix for all requests.
        timeout:         Request timeout. Override for providers with slow APIs.
        default_headers: Headers added to every request (e.g. User-Agent).

    Usage:
        client = build_http_client("https://api.moyasar.com/v1")
        # Store on the adapter instance; do not recreate per request.
    """
    headers = {
        "User-Agent": "yasargold-commerce/1.0 (httpx)",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if default_headers:
        headers.update(default_headers)

    return httpx.Client(
        base_url=base_url,
        timeout=timeout,
        headers=headers,
        verify=True,  # TLS verification always on
    )
