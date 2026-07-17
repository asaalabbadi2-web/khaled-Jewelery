"""MoyasarGateway — Adapter implementing PaymentGateway for Moyasar.

ADR-009: This file is the ONLY place in the codebase that knows:
  - Moyasar's REST API endpoint and authentication scheme
  - JSON field names in Moyasar's request/response format
  - Moyasar's HMAC-SHA256 webhook signature format
  - Moyasar's payment status vocabulary ("paid", "failed", "initiated", …)
  - Moyasar-specific error codes and retry semantics

Nothing above leaks into packages/domain. The domain sees only:
  PaymentGateway.initiate()  → CheckoutUrl
  PaymentGateway.parse_webhook() → WebhookResult

Replacing Moyasar with Tap/HyperPay = new file here, zero domain changes.

Moyasar API reference:
  Base URL:  https://api.moyasar.com/v1
  Auth:      HTTP Basic (api_key as username, empty password)
  Amounts:   Integer halalas (SAR × 100)
  Idempotency: Idempotency-Key header (payment_intent_id used as key)
  Webhook:   POST to callback_url; body = payment object JSON
  Signature: X-Moyasar-Signature header = HMAC-SHA256(secret_key, raw_body)

Environment variables expected (loaded by the app layer, not here):
  MOYASAR_API_KEY     — publishable key for payment creation
  MOYASAR_SECRET_KEY  — secret key for webhook signature verification
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from yasargold_domain.payment.gateway import CheckoutUrl, WebhookResult
from yasargold_domain.payment.intent import PaymentIntent
from yasargold_domain.shared.identifiers import PaymentFailureReason

from yasargold_commerce.infra.http_client import (
    _ProviderHttpError,
    _log_request,
    _log_response,
    _with_retry,
    build_http_client,
)

logger = logging.getLogger(__name__)

_MOYASAR_BASE = "https://api.moyasar.com/v1"
_PROVIDER_NAME = "moyasar"

# Moyasar statuses that map to outcome="paid"
_PAID_STATUSES = frozenset({"paid", "authorized"})

# Moyasar statuses that map to outcome="failed"
_FAILED_STATUSES = frozenset({"failed", "voided", "refunded", "captured"})


class MoyasarSignatureError(Exception):
    """Raised when the webhook HMAC signature does not match."""


class MoyasarGateway:
    """Production adapter for Moyasar payment gateway.

    Stateless per request. Thread-safe when httpx.Client is reused.

    Args:
        api_key:    Moyasar publishable key (starts with "pk_").
        secret_key: Moyasar secret key for HMAC verification (starts with "sk_").
        client:     Optional pre-configured httpx.Client. Defaults to the
                    shared client from http_client.build_http_client(). Pass
                    a custom client in tests to avoid network calls.
    """

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self._secret_key = secret_key
        self._client = client or build_http_client(_MOYASAR_BASE)

    # ------------------------------------------------------------------
    # PaymentGateway.initiate()
    # ------------------------------------------------------------------

    def initiate(self, intent: PaymentIntent, callback_url: str) -> CheckoutUrl:
        """Create a Moyasar payment and return the hosted checkout URL.

        Uses intent.id as the Idempotency-Key so retries after a network
        timeout never double-charge the customer.

        Amount conversion: Decimal SAR → integer halalas (× 100).

        Returns:
            CheckoutUrl with:
              url                = Moyasar's transaction_url (redirect customer here)
              provider_reference = Moyasar payment id ("pay_…")
        """
        amount_halalas = int(intent.amount * 100)

        body = {
            "amount": amount_halalas,
            "currency": intent.currency,
            "description": f"Gold reservation {intent.reservation_id}",
            "callback_url": callback_url,
            "metadata": {
                "payment_intent_id": str(intent.id),
                "reservation_id": str(intent.reservation_id),
            },
            "source": {
                "type": "creditcard",
            },
        }

        url = "/payments"
        start = _log_request("POST", f"{_MOYASAR_BASE}{url}")
        try:
            response = _with_retry(
                self._client.post,
                _PROVIDER_NAME,
                url,
                json=body,
                auth=(self._api_key, ""),
                headers={"Idempotency-Key": str(intent.id)},
            )
            _log_response("POST", f"{_MOYASAR_BASE}{url}", response.status_code, start)
        except _ProviderHttpError as exc:
            _log_response("POST", f"{_MOYASAR_BASE}{url}", exc.status_code, start)
            raise

        data = response.json()
        return CheckoutUrl(
            url=data["source"]["transaction_url"],
            provider_reference=data["id"],
        )

    # ------------------------------------------------------------------
    # PaymentGateway.parse_webhook()
    # ------------------------------------------------------------------

    def parse_webhook(self, payload: bytes, signature: str) -> WebhookResult:
        """Verify Moyasar's HMAC-SHA256 signature and parse the webhook body.

        Signature algorithm:
            HMAC-SHA256(key=secret_key, msg=raw_payload_bytes)
            Header: X-Moyasar-Signature: <hex_digest>

        Raises:
            MoyasarSignatureError: if signature verification fails.
            json.JSONDecodeError:  if payload is not valid JSON.
            KeyError:              if required fields are missing from payload.

        Returns:
            WebhookResult with outcome="paid" or "failed".
            outcome="paid" only for Moyasar statuses in _PAID_STATUSES.
            All other statuses map to outcome="failed".
        """
        self._verify_signature(payload, signature)
        data = json.loads(payload)
        return self._parse_payment_object(data)

    # ------------------------------------------------------------------
    # Internal translation methods
    # ------------------------------------------------------------------

    def _verify_signature(self, payload: bytes, signature: str) -> None:
        expected = hmac.new(
            self._secret_key.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            logger.warning("Moyasar webhook signature mismatch — possible replay attack")
            raise MoyasarSignatureError(
                "Webhook HMAC-SHA256 signature does not match"
            )

    def _parse_payment_object(self, data: dict) -> WebhookResult:
        """Translate a Moyasar payment JSON object into a domain WebhookResult.

        Moyasar status → domain outcome mapping:
          paid / authorized  → "paid"
          anything else      → "failed"

        paid_at: parsed from data["paid_at"] if present, else data["updated_at"].
        All timestamps are assumed UTC if no timezone info.
        """
        provider_reference: str = data["id"]
        moyasar_status: str = data.get("status", "")

        if moyasar_status in _PAID_STATUSES:
            outcome = "paid"
            paid_at = _parse_moyasar_datetime(
                data.get("paid_at") or data.get("updated_at")
            )
            failure_reason = None
        else:
            outcome = "failed"
            paid_at = None
            failure_reason = PaymentFailureReason(moyasar_status or "unknown")

        return WebhookResult(
            provider_reference=provider_reference,
            outcome=outcome,
            paid_at=paid_at,
            failure_reason=failure_reason,
        )


# ---------------------------------------------------------------------------
# Module-level helpers — private to this file
# ---------------------------------------------------------------------------

def _parse_moyasar_datetime(value: str | None) -> datetime | None:
    """Parse a Moyasar ISO-8601 timestamp string into a UTC-aware datetime."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        logger.warning("Could not parse Moyasar datetime: %r", value)
        return None
