"""Unit tests for MoyasarGateway — zero network calls.

Uses httpx.MockTransport to intercept HTTP calls inside the adapter.
Tests verify the translation layer only:
  - SAR → halalas conversion
  - Idempotency-Key header is the payment_intent_id
  - Moyasar JSON → CheckoutUrl mapping
  - Moyasar webhook JSON → WebhookResult mapping
  - HMAC-SHA256 signature verification (valid + invalid)
  - Error status code handling (4xx, 5xx)
  - Moyasar status → domain outcome mapping ("paid", "failed", etc.)
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest

from yasargold_domain.payment.intent import PaymentIntent, PaymentStatus
from yasargold_domain.payment.gateway import CheckoutUrl, WebhookResult
from yasargold_domain.shared.identifiers import (
    PaymentFailureReason,
    PaymentIntentId,
    PaymentProvider,
    ReservationId,
)

from yasargold_commerce.infra.moyasar_gateway import (
    MoyasarGateway,
    MoyasarSignatureError,
    _parse_moyasar_datetime,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_API_KEY = "pk_test_abc123"
_SECRET_KEY = "sk_test_xyz789"
_NOW = datetime(2026, 7, 13, 14, 0, 0, tzinfo=timezone.utc)
_INTENT_ID = PaymentIntentId("pi_test0001abc12345")
_RES_ID = ReservationId("res_abc123")
_AMOUNT = Decimal("5500.00")
_CALLBACK = "https://commerce.yasargold.com/webhooks/payment"
_MOYASAR_PAY_ID = "pay_moyasar_123456"
_TRANSACTION_URL = "https://api.moyasar.com/v1/payments/pay_moyasar_123456/sources/creditcard"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_intent(amount: Decimal = _AMOUNT) -> PaymentIntent:
    return PaymentIntent(
        id=_INTENT_ID,
        reservation_id=_RES_ID,
        amount=amount,
        currency="SAR",
        status=PaymentStatus.PENDING,
        created_at=_NOW,
        expires_at=_NOW,
    )


def _moyasar_payment_response(status: str = "initiated") -> dict:
    return {
        "id": _MOYASAR_PAY_ID,
        "status": status,
        "amount": 550000,
        "currency": "SAR",
        "source": {
            "type": "creditcard",
            "transaction_url": _TRANSACTION_URL,
        },
        "paid_at": "2026-07-13T14:05:00+00:00",
        "updated_at": "2026-07-13T14:00:01+00:00",
    }


def _make_mock_client(
    status_code: int = 200,
    body: dict | None = None,
) -> httpx.Client:
    """Return an httpx.Client with a MockTransport that returns a fixed response."""
    response_body = json.dumps(body or _moyasar_payment_response()).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=status_code,
            content=response_body,
            headers={"Content-Type": "application/json"},
        )

    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport, base_url="https://api.moyasar.com/v1")


def _make_gateway(client: httpx.Client | None = None) -> MoyasarGateway:
    return MoyasarGateway(_API_KEY, _SECRET_KEY, client=client or _make_mock_client())


def _sign_payload(payload: bytes, secret: str = _SECRET_KEY) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def _make_webhook_payload(status: str = "paid") -> bytes:
    data = {
        "id": _MOYASAR_PAY_ID,
        "status": status,
        "amount": 550000,
        "currency": "SAR",
        "paid_at": "2026-07-13T14:05:00+00:00" if status == "paid" else None,
        "updated_at": "2026-07-13T14:05:00+00:00",
    }
    return json.dumps(data).encode()


# ---------------------------------------------------------------------------
# initiate() — happy path
# ---------------------------------------------------------------------------

class TestInitiateHappyPath:
    def test_returns_checkout_url(self) -> None:
        gw = _make_gateway()
        result = gw.initiate(_make_intent(), _CALLBACK)
        assert isinstance(result, CheckoutUrl)
        assert result.url == _TRANSACTION_URL

    def test_returns_moyasar_payment_id_as_provider_reference(self) -> None:
        gw = _make_gateway()
        result = gw.initiate(_make_intent(), _CALLBACK)
        assert result.provider_reference == _MOYASAR_PAY_ID

    def test_amount_converted_to_halalas(self) -> None:
        """5500.00 SAR must be sent as 550000 halalas."""
        captured: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(json.loads(request.content))
            return httpx.Response(
                200,
                json=_moyasar_payment_response(),
                headers={"Content-Type": "application/json"},
            )

        client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.moyasar.com/v1")
        gw = MoyasarGateway(_API_KEY, _SECRET_KEY, client=client)
        gw.initiate(_make_intent(Decimal("5500.00")), _CALLBACK)

        assert captured[0]["amount"] == 550000

    def test_idempotency_key_is_payment_intent_id(self) -> None:
        captured_headers: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_headers.append(dict(request.headers))
            return httpx.Response(
                200,
                json=_moyasar_payment_response(),
                headers={"Content-Type": "application/json"},
            )

        client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.moyasar.com/v1")
        gw = MoyasarGateway(_API_KEY, _SECRET_KEY, client=client)
        gw.initiate(_make_intent(), _CALLBACK)

        assert captured_headers[0].get("idempotency-key") == str(_INTENT_ID)

    def test_metadata_carries_payment_intent_id(self) -> None:
        captured: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(json.loads(request.content))
            return httpx.Response(200, json=_moyasar_payment_response(), headers={"Content-Type": "application/json"})

        client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.moyasar.com/v1")
        gw = MoyasarGateway(_API_KEY, _SECRET_KEY, client=client)
        gw.initiate(_make_intent(), _CALLBACK)

        assert captured[0]["metadata"]["payment_intent_id"] == str(_INTENT_ID)
        assert captured[0]["metadata"]["reservation_id"] == str(_RES_ID)


# ---------------------------------------------------------------------------
# initiate() — error handling
# ---------------------------------------------------------------------------

class TestInitiateErrors:
    def test_moyasar_400_raises_provider_error(self) -> None:
        from yasargold_commerce.infra.http_client import _ProviderHttpError
        gw = _make_gateway(_make_mock_client(400, {"message": "invalid amount"}))
        with pytest.raises(_ProviderHttpError) as exc_info:
            gw.initiate(_make_intent(), _CALLBACK)
        assert exc_info.value.status_code == 400

    def test_moyasar_401_raises_provider_error(self) -> None:
        from yasargold_commerce.infra.http_client import _ProviderHttpError
        gw = _make_gateway(_make_mock_client(401, {"message": "unauthorized"}))
        with pytest.raises(_ProviderHttpError) as exc_info:
            gw.initiate(_make_intent(), _CALLBACK)
        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# parse_webhook() — happy path (paid)
# ---------------------------------------------------------------------------

class TestParseWebhookPaid:
    def test_paid_status_returns_paid_outcome(self) -> None:
        payload = _make_webhook_payload("paid")
        sig = _sign_payload(payload)
        result = _make_gateway().parse_webhook(payload, sig)
        assert result.outcome == "paid"

    def test_authorized_status_returns_paid_outcome(self) -> None:
        payload = _make_webhook_payload("authorized")
        sig = _sign_payload(payload)
        result = _make_gateway().parse_webhook(payload, sig)
        assert result.outcome == "paid"

    def test_provider_reference_extracted(self) -> None:
        payload = _make_webhook_payload("paid")
        sig = _sign_payload(payload)
        result = _make_gateway().parse_webhook(payload, sig)
        assert result.provider_reference == _MOYASAR_PAY_ID

    def test_paid_at_parsed_from_webhook(self) -> None:
        payload = _make_webhook_payload("paid")
        sig = _sign_payload(payload)
        result = _make_gateway().parse_webhook(payload, sig)
        assert result.paid_at is not None
        assert result.paid_at.year == 2026
        assert result.paid_at.tzinfo is not None

    def test_failure_reason_is_none_on_paid(self) -> None:
        payload = _make_webhook_payload("paid")
        sig = _sign_payload(payload)
        result = _make_gateway().parse_webhook(payload, sig)
        assert result.failure_reason is None


# ---------------------------------------------------------------------------
# parse_webhook() — failed outcomes
# ---------------------------------------------------------------------------

class TestParseWebhookFailed:
    @pytest.mark.parametrize("status", ["failed", "voided", "refunded"])
    def test_non_paid_status_returns_failed_outcome(self, status: str) -> None:
        payload = _make_webhook_payload(status)
        sig = _sign_payload(payload)
        result = _make_gateway().parse_webhook(payload, sig)
        assert result.outcome == "failed"

    def test_failure_reason_carries_moyasar_status(self) -> None:
        payload = _make_webhook_payload("failed")
        sig = _sign_payload(payload)
        result = _make_gateway().parse_webhook(payload, sig)
        assert result.failure_reason == PaymentFailureReason("failed")

    def test_paid_at_is_none_on_failed(self) -> None:
        payload = _make_webhook_payload("failed")
        sig = _sign_payload(payload)
        result = _make_gateway().parse_webhook(payload, sig)
        assert result.paid_at is None


# ---------------------------------------------------------------------------
# parse_webhook() — signature verification
# ---------------------------------------------------------------------------

class TestSignatureVerification:
    def test_valid_signature_accepted(self) -> None:
        payload = _make_webhook_payload("paid")
        sig = _sign_payload(payload)
        result = _make_gateway().parse_webhook(payload, sig)
        assert result.outcome == "paid"

    def test_invalid_signature_raises(self) -> None:
        payload = _make_webhook_payload("paid")
        bad_sig = "0" * 64
        with pytest.raises(MoyasarSignatureError):
            _make_gateway().parse_webhook(payload, bad_sig)

    def test_wrong_secret_raises(self) -> None:
        payload = _make_webhook_payload("paid")
        sig_with_wrong_key = _sign_payload(payload, secret="wrong_secret_key")
        with pytest.raises(MoyasarSignatureError):
            _make_gateway().parse_webhook(payload, sig_with_wrong_key)

    def test_tampered_payload_raises(self) -> None:
        original = _make_webhook_payload("paid")
        sig = _sign_payload(original)
        tampered = original.replace(b'"paid"', b'"failed"')
        with pytest.raises(MoyasarSignatureError):
            _make_gateway().parse_webhook(tampered, sig)


# ---------------------------------------------------------------------------
# _parse_moyasar_datetime helper
# ---------------------------------------------------------------------------

class TestParseMoyasarDatetime:
    def test_iso_string_with_offset(self) -> None:
        dt = _parse_moyasar_datetime("2026-07-13T14:05:00+00:00")
        assert dt is not None
        assert dt.tzinfo is not None
        assert dt.year == 2026

    def test_naive_string_gets_utc(self) -> None:
        dt = _parse_moyasar_datetime("2026-07-13T14:05:00")
        assert dt is not None
        assert dt.tzinfo == timezone.utc

    def test_none_returns_none(self) -> None:
        assert _parse_moyasar_datetime(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert _parse_moyasar_datetime("") is None
