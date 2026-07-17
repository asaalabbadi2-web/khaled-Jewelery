"""TwilioNotificationGateway — NotificationGateway adapter for Twilio SMS.

ADR-019 requirements:
  ① Timeout       — every HTTP call uses DEFAULT_TIMEOUT via build_http_client
  ② Retry         — retry budget = 0 for SMS (ADR-019 §Watch Out For)
                    Duplicate sends cannot be undone. On any failure,
                    raise NotificationGatewayError immediately; the worker
                    records FAILED and the caller decides whether to retry
                    via a new Notification record.
  ③ Idempotency   — idempotency_key passed as X-Twilio-Idempotency-Token
                    header. Twilio deduplicates on their side when present.
  ④ Correlation   — X-Correlation-Id: uuid4 per call, logged for incident tracing
  ⑤ Metrics       — SMS_DISPATCH_SUCCESS / FAILURE / DURATION per call
  ⑥ Probe         — probe() GETs /Accounts/{account_sid} (read-only, no side-effects)

Channel support:
  SMS only. Passing EMAIL / WHATSAPP / PUSH raises NotificationGatewayError
  immediately (wrong provider — use the correct adapter for that channel).

Template resolution:
  NotificationTemplate → Arabic SMS body. Variables substituted via str.format_map().
  Templates are intentionally bilingual-ready — add a language parameter in v2
  if multi-language support is required.

Twilio API reference:
  Base URL: https://api.twilio.com/2010-04-01
  Auth:     HTTP Basic (account_sid as username, auth_token as password)
  Endpoint: POST /Accounts/{account_sid}/Messages.json
  Body:     application/x-www-form-urlencoded  (From, To, Body)
  Success:  201 — {"sid": "SMabc...", "status": "queued", ...}
  Error:    4xx/5xx — {"code": 21211, "message": "...", "status": 400}

Environment variables (loaded by the app layer, not here):
  TWILIO_ACCOUNT_SID
  TWILIO_AUTH_TOKEN
  TWILIO_FROM_NUMBER   — E.164 phone number or Messaging Service SID
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
    SMS_DISPATCH_DURATION,
    SMS_DISPATCH_FAILURE,
    SMS_DISPATCH_SUCCESS,
)
from yasargold_domain.notifications.channels import NotificationChannel, NotificationTemplate
from yasargold_domain.notifications.exceptions import NotificationGatewayError

log = logging.getLogger(__name__)

_TWILIO_BASE = "https://api.twilio.com/2010-04-01"

# SMS template bodies — Arabic, variable substitution via str.format_map()
_SMS_BODIES: dict[NotificationTemplate, str] = {
    NotificationTemplate.ORDER_CONFIRMED: (
        "مرحباً! طلبك رقم {order_id} تم تأكيده بمبلغ {amount} {currency}. "
        "شكراً لثقتك بيسار الذهب."
    ),
    NotificationTemplate.ORDER_CANCELLED: (
        "نأسف، تم إلغاء طلبك رقم {order_id}. "
        "للاستفسار يرجى التواصل مع خدمة العملاء."
    ),
    NotificationTemplate.REFUND_INITIATED: (
        "تمّت معالجة طلب الاسترداد لطلبك رقم {order_id} "
        "بمبلغ {amount} {currency}. سيظهر في حسابك خلال 5-7 أيام عمل."
    ),
    NotificationTemplate.RESERVATION_EXPIRY: (
        "تذكير: حجزك سينتهي قريباً. "
        "أتمّ الدفع الآن للحفاظ على سعر الذهب المقفول."
    ),
}

# Permanent 4xx Twilio error codes that should never be retried
_PERMANENT_HTTP_CODES = frozenset({400, 401, 403, 404, 422})


class TwilioNotificationGateway:
    """Implements NotificationGateway by calling Twilio POST .../Messages.json.

    Retry budget is 0 (SMS cannot be safely retried without provider idempotency
    on every platform). On failure, raise NotificationGatewayError immediately;
    the NotificationWorker records FAILED and owns the retry decision.

    Args:
        account_sid:  Twilio Account SID (starts with "AC").
        auth_token:   Twilio Auth Token.
        from_number:  E.164 phone number or Messaging Service SID (MS...).
        client:       Optional pre-configured httpx.Client (pass in tests to
                      avoid network calls — same pattern as MoyasarGateway).
    """

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        from_number: str,
        client: httpx.Client | None = None,
    ) -> None:
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._from_number = from_number
        self._client = client or build_http_client(
            _TWILIO_BASE,
            default_headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    def send(
        self,
        channel: NotificationChannel,
        recipient: str,
        template: NotificationTemplate,
        variables: dict[str, str],
        idempotency_key: str | None = None,
    ) -> str:
        """Send an SMS via Twilio. Only NotificationChannel.SMS is supported.

        Returns:
            Twilio message SID (e.g. "SMabc...") for audit.

        Raises:
            NotificationGatewayError: any failure — no internal retry.
        """
        if channel != NotificationChannel.SMS:
            raise NotificationGatewayError(
                channel.value,
                f"TwilioNotificationGateway only supports SMS; received {channel.value}",
            )

        body_template = _SMS_BODIES.get(template)
        if body_template is None:
            raise NotificationGatewayError(
                channel.value,
                f"No SMS template configured for {template.value}",
            )

        message_body = body_template.format_map(variables)
        correlation_id = str(uuid.uuid4())
        url = f"/Accounts/{self._account_sid}/Messages.json"

        log.info(
            "twilio_sms: sending template=%s recipient=%s correlation_id=%s",
            template.value,
            recipient,
            correlation_id,
        )

        _op_start = time.monotonic()
        req_start = _log_request("POST", f"{_TWILIO_BASE}{url}")

        try:
            response = self._client.post(
                url,
                data={
                    "From": self._from_number,
                    "To": recipient,
                    "Body": message_body,
                },
                auth=(self._account_sid, self._auth_token),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-Twilio-Idempotency-Token": idempotency_key or "",
                    "X-Correlation-Id": correlation_id,
                },
            )
            _log_response("POST", f"{_TWILIO_BASE}{url}", response.status_code, req_start)

        except httpx.TimeoutException as exc:
            SMS_DISPATCH_DURATION.observe(time.monotonic() - _op_start)
            SMS_DISPATCH_FAILURE.labels(kind="transient").inc()
            log.warning(
                "twilio_sms: timeout template=%s recipient=%s correlation_id=%s",
                template.value, recipient, correlation_id,
            )
            raise NotificationGatewayError(channel.value, f"timeout: {exc}") from exc

        except (httpx.ConnectError, httpx.NetworkError) as exc:
            SMS_DISPATCH_DURATION.observe(time.monotonic() - _op_start)
            SMS_DISPATCH_FAILURE.labels(kind="transient").inc()
            log.warning(
                "twilio_sms: network error template=%s recipient=%s correlation_id=%s error=%s",
                template.value, recipient, correlation_id, exc,
            )
            raise NotificationGatewayError(channel.value, f"network: {exc}") from exc

        status = response.status_code

        if status == 201:
            SMS_DISPATCH_DURATION.observe(time.monotonic() - _op_start)
            SMS_DISPATCH_SUCCESS.inc()
            sid = response.json().get("sid", "")
            log.info(
                "twilio_sms: sent sid=%s template=%s recipient=%s correlation_id=%s",
                sid, template.value, recipient, correlation_id,
            )
            return sid

        # Any non-201 is an error — no retry regardless of 4xx or 5xx
        kind = "permanent" if status in _PERMANENT_HTTP_CODES else "transient"
        SMS_DISPATCH_DURATION.observe(time.monotonic() - _op_start)
        SMS_DISPATCH_FAILURE.labels(kind=kind).inc()

        try:
            error_body = response.json()
            reason = f"HTTP {status}: code={error_body.get('code')} {error_body.get('message', '')}"
        except Exception:
            reason = f"HTTP {status}: {response.text[:200]}"

        log.warning(
            "twilio_sms: failed status=%d kind=%s template=%s recipient=%s correlation_id=%s",
            status, kind, template.value, recipient, correlation_id,
        )
        raise NotificationGatewayError(channel.value, reason)

    def probe(self) -> bool:
        """Return True if Twilio API is reachable and credentials are valid.

        GETs /Accounts/{account_sid} — read-only, no side-effects, no SMS sent.
        Returns False on 401 (wrong credentials) or any network error.
        """
        try:
            response = self._client.get(
                f"/Accounts/{self._account_sid}.json",
                auth=(self._account_sid, self._auth_token),
            )
            return response.status_code == 200
        except (httpx.ConnectError, httpx.NetworkError, httpx.TimeoutException):
            return False
