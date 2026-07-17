"""Payments router — POST /api/v1/payments + POST /api/v1/webhooks/payment.

HTTP layer responsibilities:
  - Validate request shape (Pydantic / Header)
  - Load reservation + item from DB to derive amount
  - Open Unit of Work and call domain services
  - Map domain exceptions to HTTP status codes
  - Record Prometheus metrics
  - Commit and return 201 / 204

HTTP layer does NOT:
  - Know which payment statuses are valid (PaymentIntent.can_pay() does)
  - Decide if a webhook should transition state (PaymentService.confirm() does)
  - Know Moyasar-specific error codes (MoyasarGateway.parse_webhook() does)
  - Know if a reservation can be confirmed (CheckoutService.confirm() does)

ADR-009: The HTTP layer sees PaymentGateway (Protocol), not MoyasarGateway.
ADR-010: Webhooks are translated here, state decisions happen in the domain.
ADR-011: CheckoutService creates the Order atomically with Reservation COMPLETED.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from decimal import Decimal
from functools import lru_cache

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, field_serializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from yasargold_commerce.auth import get_customer_ref
from yasargold_commerce.db import get_db
from yasargold_commerce.infra.checkout_uow import SQLAlchemyCheckoutUnitOfWork
from yasargold_commerce.infra.moyasar_gateway import MoyasarGateway, MoyasarSignatureError
from yasargold_commerce.infra.payment_uow import SQLAlchemyPaymentUnitOfWork
from yasargold_commerce.infra.reservation_uow import SQLAlchemyReservationUnitOfWork
from yasargold_commerce.metrics import (
    ORDER_CREATED,
    PAYMENT_FAILED,
    PAYMENT_GATEWAY_FAILURES,
    PAYMENT_GATEWAY_REQUEST_DURATION,
    PAYMENT_INTENT_CREATED,
    PAYMENT_RECEIVED,
    PAYMENT_WEBHOOK_LATENCY,
    RESERVATION_CONFIRMED,
    RESERVATION_LIFETIME_SECONDS,
)
from yasargold_commerce.models import Item
from yasargold_domain.orders.unit_of_work import CheckoutUnitOfWork
from yasargold_domain.payment.exceptions import (
    PaymentIntentExpiredError,
    PaymentIntentNotFoundException,
    PaymentIntentStatusError,
)
from yasargold_domain.payment.gateway import PaymentGateway
from yasargold_domain.payment.service import PaymentService
from yasargold_domain.payment.unit_of_work import PaymentUnitOfWork
from yasargold_domain.pricing.reservation_policy import CompositePolicy
from yasargold_domain.reservation.checkout_service import CheckoutService
from yasargold_domain.reservation.exceptions import (
    ReservationExpiredError,
    ReservationNotFoundException,
    ReservationStatusError,
)
from yasargold_domain.reservation.service import ReservationService
from yasargold_domain.reservation.unit_of_work import ReservationUnitOfWork
from yasargold_domain.shared.identifiers import ReservationId
from yasargold_commerce.infra.reservation_orm import ReservationRow

router = APIRouter(prefix="/api/v1", tags=["payments"])

_checkout_service = CheckoutService()
# Stateless service instance — policy not used for find_reservation_for_customer
_res_service = ReservationService(policy=CompositePolicy(policies=[]))

# ---------------------------------------------------------------------------
# Dependency providers (overridable in contract tests)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _build_gateway() -> MoyasarGateway:
    return MoyasarGateway(
        api_key=os.environ["MOYASAR_API_KEY"],
        secret_key=os.environ["MOYASAR_SECRET_KEY"],
    )


def _get_gateway() -> PaymentGateway:
    return _build_gateway()


def _get_payment_service(gateway: PaymentGateway = Depends(_get_gateway)) -> PaymentService:
    return PaymentService(gateway)


def _get_payment_uow(db: Session = Depends(get_db)) -> PaymentUnitOfWork:
    return SQLAlchemyPaymentUnitOfWork(db)


def _get_checkout_uow(db: Session = Depends(get_db)) -> CheckoutUnitOfWork:
    return SQLAlchemyCheckoutUnitOfWork(db)


def _get_reservation_service() -> ReservationService:
    return _res_service


def _get_reservation_uow(db: Session = Depends(get_db)) -> ReservationUnitOfWork:
    return SQLAlchemyReservationUnitOfWork(db)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CreatePaymentRequest(BaseModel):
    reservation_id: str


class PaymentIntentCreatedResponse(BaseModel):
    payment_intent_id: str
    checkout_url: str
    expires_at: datetime
    provider: str = "moyasar"

    @field_serializer("expires_at")
    def _serialize_dt(self, v: datetime) -> str:
        return v.isoformat()


# ---------------------------------------------------------------------------
# POST /api/v1/payments
# ---------------------------------------------------------------------------

@router.post(
    "/payments",
    response_model=PaymentIntentCreatedResponse,
    status_code=201,
    summary="Create a PaymentIntent and open a Moyasar checkout session",
    responses={
        404: {"description": "Reservation or item not found"},
        409: {"description": "Payment already initiated for this reservation"},
        422: {"description": "Reservation expired or in invalid state"},
        502: {"description": "Payment gateway unavailable"},
    },
)
def create_payment(
    body: CreatePaymentRequest,
    db: Session = Depends(get_db),
    payment_service: PaymentService = Depends(_get_payment_service),
    payment_uow: PaymentUnitOfWork = Depends(_get_payment_uow),
    res_service: ReservationService = Depends(_get_reservation_service),
    res_uow: ReservationUnitOfWork = Depends(_get_reservation_uow),
    customer_ref: str = Depends(get_customer_ref),
) -> PaymentIntentCreatedResponse:
    """Open a payment session for an existing reservation.

    BOLA (Law 5): ownership check lives in domain service, not in router.
    Router maps None → 404. 403 would confirm the reservation exists — oracle attack.
    """
    now = datetime.now(timezone.utc)
    reservation_id = ReservationId(body.reservation_id)

    # Law 5: delegate ownership check to the domain service
    with res_uow:
        record = res_service.find_reservation_for_customer(reservation_id, customer_ref, res_uow)
    if record is None:
        raise HTTPException(status_code=404, detail="Reservation not found")

    item = db.execute(
        select(Item).where(Item.id == str(record.item_id))
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    amount = Decimal(str(item.price))
    callback_url = f"{os.environ.get('COMMERCE_API_BASE_URL', 'https://api.yasargold.com')}/api/v1/webhooks/payment"

    gateway_start = time.monotonic()
    try:
        with payment_uow:
            intent, checkout_url = payment_service.issue(
                reservation_id=reservation_id,
                amount=amount,
                currency="SAR",
                expires_at=record.valid_until,
                callback_url=callback_url,
                uow=payment_uow,
                now=now,
            )
            payment_uow.commit()
    except Exception as exc:
        elapsed = time.monotonic() - gateway_start
        PAYMENT_GATEWAY_REQUEST_DURATION.labels(provider="moyasar").observe(elapsed)
        PAYMENT_GATEWAY_FAILURES.labels(
            provider="moyasar",
            error_type=_classify_gateway_error(exc),
        ).inc()
        raise HTTPException(status_code=502, detail="Payment gateway unavailable") from exc

    elapsed = time.monotonic() - gateway_start
    PAYMENT_GATEWAY_REQUEST_DURATION.labels(provider="moyasar").observe(elapsed)
    PAYMENT_INTENT_CREATED.inc()

    return PaymentIntentCreatedResponse(
        payment_intent_id=str(intent.id),
        checkout_url=checkout_url,
        expires_at=intent.expires_at,
        provider="moyasar",
    )


# ---------------------------------------------------------------------------
# POST /api/v1/webhooks/payment
# ---------------------------------------------------------------------------

@router.post(
    "/webhooks/payment",
    status_code=204,
    summary="Receive and process a Moyasar payment webhook",
    responses={
        204: {"description": "Webhook processed (idempotent)"},
        400: {"description": "Invalid signature or malformed payload"},
        404: {"description": "PaymentIntent not found for provider_reference"},
    },
)
async def payment_webhook(
    request: Request,
    db: Session = Depends(get_db),
    gateway: PaymentGateway = Depends(_get_gateway),
    payment_service: PaymentService = Depends(_get_payment_service),
    payment_uow: PaymentUnitOfWork = Depends(_get_payment_uow),
    checkout_uow: CheckoutUnitOfWork = Depends(_get_checkout_uow),
    x_moyasar_signature: str = Header(..., alias="X-Moyasar-Signature"),
) -> None:
    """Translate Moyasar webhook → domain state transitions.

    ADR-010: This handler translates. It never makes state decisions.
    ADR-011: CheckoutService creates Order + completes Reservation atomically.

    Idempotency:
      - PaymentIntentStatusError (already PAID/FAILED) → 204
      - ReservationStatusError (already COMPLETED)     → 204
    """
    webhook_start = time.monotonic()
    now = datetime.now(timezone.utc)

    # Step 1: Verify signature and parse (ADR-010: translate only)
    payload = await request.body()
    try:
        webhook_result = gateway.parse_webhook(payload, x_moyasar_signature)
    except MoyasarSignatureError:
        raise HTTPException(status_code=400, detail="Invalid webhook signature")
    except Exception:
        raise HTTPException(status_code=400, detail="Malformed webhook payload")

    # Step 2: Transition PaymentIntent state (own transaction)
    try:
        with payment_uow:
            intent = payment_service.confirm(webhook_result, payment_uow, now=now)
            payment_uow.commit()
    except PaymentIntentNotFoundException:
        raise HTTPException(status_code=404, detail="PaymentIntent not found")
    except PaymentIntentStatusError:
        return  # Already processed — idempotent 204
    except PaymentIntentExpiredError:
        return  # Expired before payment arrived — 204

    # Step 3: Record payment metrics
    if intent.status.value == "PAID":
        PAYMENT_RECEIVED.inc()
    else:
        PAYMENT_FAILED.labels(
            failure_reason=str(intent.failure_reason or "unknown")
        ).inc()

    # Step 4: ADR-013 Condition 1 — second ERP availability check.
    # Reduces the race window from the full reservation lifetime (15 min)
    # to the seconds between this check and payment capture.
    # Must run BEFORE checkout so we never create an order for a sold item.
    if intent.can_confirm():
        res_row = db.execute(
            select(ReservationRow).where(ReservationRow.id == str(intent.reservation_id))
        ).scalar_one_or_none()
        if res_row is not None:
            item_row = db.execute(
                select(Item).where(Item.id == res_row.item_id)
            ).scalar_one_or_none()
            if item_row is None or not item_row.stock or item_row.stock <= 0:
                # Item sold at POS after reservation was created — compensation path.
                with payment_uow:
                    payment_service.mark_refund_pending(intent, payment_uow)
                    payment_uow.commit()
                return  # RefundWorker picks up REFUND_PENDING → REFUNDED

    # Step 5: Create Order + complete Reservation atomically (ADR-011)
    if intent.can_confirm():
        try:
            with checkout_uow:
                reservation, order = _checkout_service.confirm(
                    reservation_id=intent.reservation_id,
                    payment_intent_id=intent.id,
                    amount=intent.amount,
                    currency=intent.currency,
                    uow=checkout_uow,
                    now=now,
                )
                checkout_uow.commit()

            RESERVATION_CONFIRMED.inc()
            ORDER_CREATED.inc()
            if reservation.reserved_at:
                lifetime = (now - reservation.reserved_at.replace(tzinfo=timezone.utc)).total_seconds()
                RESERVATION_LIFETIME_SECONDS.labels(outcome="confirmed").observe(lifetime)
        except (ReservationStatusError, ReservationExpiredError, ReservationNotFoundException):
            pass  # Already confirmed or expired — idempotent

    elapsed = time.monotonic() - webhook_start
    PAYMENT_WEBHOOK_LATENCY.observe(elapsed)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _classify_gateway_error(exc: Exception) -> str:
    from yasargold_commerce.infra.http_client import _ProviderHttpError
    import httpx
    if isinstance(exc, _ProviderHttpError):
        return "http_4xx" if exc.status_code < 500 else "http_5xx"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    return "network"
