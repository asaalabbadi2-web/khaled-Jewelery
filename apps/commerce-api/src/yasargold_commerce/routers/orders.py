"""Orders router — GET /api/v1/orders/{order_id}.

Read-only for Sprint 5. Write operations (cancel, ship, deliver) are added
in Sprint 7 when the Shipping capability is built.

The Order is the Business Record (ADR-011): every downstream capability
(Shipping, Notifications, ERP Sync, Analytics) reads from this endpoint.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_serializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from yasargold_commerce.auth import get_customer_ref
from yasargold_commerce.db import get_db
from yasargold_commerce.infra.order_orm import OrderRow
from yasargold_commerce.infra.order_uow import SQLAlchemyOrderUnitOfWork
from yasargold_domain.orders.service import OrderService
from yasargold_domain.shared.identifiers import OrderId, ReservationId

router = APIRouter(prefix="/api/v1", tags=["orders"])

_order_service = OrderService()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class OrderResponse(BaseModel):
    order_id: str
    reservation_id: str
    payment_intent_id: str
    item_id: int
    amount: str
    currency: str
    status: str
    created_at: datetime
    confirmed_at: datetime | None = None
    shipped_at: datetime | None = None
    delivered_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None

    @field_serializer("created_at", "confirmed_at", "shipped_at", "delivered_at", "cancelled_at")
    def _serialize_dt(self, v: datetime | None) -> str | None:
        return v.isoformat() if v is not None else None


# ---------------------------------------------------------------------------
# GET /api/v1/orders/{order_id}
# ---------------------------------------------------------------------------

@router.get(
    "/orders/{order_id}",
    response_model=OrderResponse,
    status_code=200,
    summary="Retrieve an Order by ID",
    responses={
        200: {"description": "Order found"},
        404: {"description": "Order not found"},
    },
)
def get_order(
    order_id: str,
    db: Session = Depends(get_db),
    customer_ref: str = Depends(get_customer_ref),
) -> OrderResponse:
    """Return the Order only if the caller owns it (Law 5 — BOLA).

    The JWT sub claim is the customer identity. Orders created before v1.4
    (customer_ref=NULL) are not accessible via this endpoint.
    """
    uow = SQLAlchemyOrderUnitOfWork(db)
    order = _order_service.find_order_for_customer(
        OrderId(order_id), customer_ref, uow
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    return OrderResponse(
        order_id=str(order.id),
        reservation_id=str(order.reservation_id),
        payment_intent_id=str(order.payment_intent_id),
        item_id=int(order.item_id),
        amount=str(order.amount),
        currency=order.currency,
        status=order.status.value,
        created_at=order.created_at,
        confirmed_at=order.confirmed_at,
        shipped_at=order.shipped_at,
        delivered_at=order.delivered_at,
        cancelled_at=order.cancelled_at,
        cancellation_reason=order.cancellation_reason,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/reservations/{reservation_id}/order
# ---------------------------------------------------------------------------

@router.get(
    "/reservations/{reservation_id}/order",
    response_model=OrderResponse,
    status_code=200,
    summary="Retrieve the Order linked to a Reservation",
    responses={
        200: {"description": "Order found"},
        404: {"description": "No Order found for this Reservation"},
    },
)
def get_order_by_reservation(
    reservation_id: str,
    db: Session = Depends(get_db),
    customer_ref: str = Depends(get_customer_ref),
) -> OrderResponse:
    """Look up an Order by Reservation, returning only if the caller owns it (BOLA)."""
    uow = SQLAlchemyOrderUnitOfWork(db)
    order = uow.repository.find_by_reservation_id(ReservationId(reservation_id))
    if order is None or order.customer_ref != customer_ref:
        raise HTTPException(status_code=404, detail="No order found for this reservation")

    return OrderResponse(
        order_id=str(order.id),
        reservation_id=str(order.reservation_id),
        payment_intent_id=str(order.payment_intent_id),
        item_id=int(order.item_id),
        amount=str(order.amount),
        currency=order.currency,
        status=order.status.value,
        created_at=order.created_at,
        confirmed_at=order.confirmed_at,
        shipped_at=order.shipped_at,
        delivered_at=order.delivered_at,
        cancelled_at=order.cancelled_at,
        cancellation_reason=order.cancellation_reason,
    )
