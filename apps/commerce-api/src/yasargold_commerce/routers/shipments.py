"""Shipments router — full shipment lifecycle for Orders.

Endpoints:
    POST   /api/v1/orders/{order_id}/shipments          create (claim-then-send)
    GET    /api/v1/orders/{order_id}/shipments          get shipment for an order
    POST   /api/v1/shipments/{shipment_id}/void         void within void_window
    POST   /api/v1/shipments/{shipment_id}/deliver      mark delivered (webhook)

SECURITY (v1.4 — Law 1 + Law 4 + Law 5 runtime enforcement):
    create, void, and deliver require a valid JWT with scope="admin".
    Auth is enforced by the require_admin dependency from auth.py.

    GET /orders/{order_id}/shipments requires scope="customer" (Law 4) AND
    ownership of the order (Law 5 — BOLA). Ownership is validated by
    _get_order_service().find_order_for_customer() before any shipment query.
    Non-owner and non-existent orders both return 404 with an identical body —
    the response never reveals whether a resource exists (no enumeration).

    Proof tests:
      tests/security/test_admin_scope_enforcement.py  — Law 1/4 (admin endpoints)
      tests/security/test_shipment_bola.py            — Law 5 (BOLA, GET shipment)

claim-then-send pattern (ADR-015):
    Phase 1: claim() saves PENDING → commit (before network call)
    Phase 2: gateway.create_shipment() → mark_created() + OrderService.ship() → commit

declared_value (§13 Frozen):
    Defaults to order.amount if not provided in the request body.
    The stored value is frozen at claim time and must not change.

void_window (§13 Live):
    Read from CarrierConfig at void decision time, not cached on the Shipment.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_serializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from yasargold_commerce.auth import get_customer_ref, require_admin
from yasargold_commerce.db import get_db
from yasargold_commerce.infra.log_shipping_gateway import LogShippingGateway
from yasargold_commerce.infra.order_orm import OrderRow
from yasargold_commerce.infra.order_uow import SQLAlchemyOrderUnitOfWork
from yasargold_commerce.infra.shipment_orm import ShipmentRow
from yasargold_commerce.infra.shipment_store import SQLAlchemyCarrierConfigRepository
from yasargold_commerce.infra.shipment_uow import SQLAlchemyShipmentUnitOfWork
from yasargold_domain.orders.exceptions import OrderNotFoundException, OrderStatusError
from yasargold_domain.orders.service import OrderService
from yasargold_domain.shipping.exceptions import (
    CannotVoidShipmentError,
    ShipmentGatewayError,
    ShipmentNotFoundException,
    ShipmentStatusError,
)
from yasargold_domain.shipping.service import ShipmentService
from yasargold_domain.shared.identifiers import OrderId, ShipmentId

router = APIRouter(prefix="/api/v1", tags=["shipments"])

_gateway = LogShippingGateway()
_shipment_service = ShipmentService(_gateway)
_order_service = OrderService()


def _get_order_service() -> OrderService:
    """Injectable OrderService — overridden in tests via app.dependency_overrides."""
    return _order_service


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CreateShipmentRequest(BaseModel):
    carrier_id: str
    declared_value: Decimal | None = None


class ShipmentResponse(BaseModel):
    shipment_id: str
    order_id: str
    carrier_id: str
    declared_value: str
    status: str
    idempotency_key: str
    tracking_number: str | None = None
    failure_reason: str | None = None
    created_at: datetime
    registered_at: datetime | None = None
    in_transit_at: datetime | None = None
    delivered_at: datetime | None = None
    voided_at: datetime | None = None

    @field_serializer(
        "created_at", "registered_at", "in_transit_at", "delivered_at", "voided_at"
    )
    def _serialize_dt(self, v: datetime | None) -> str | None:
        return v.isoformat() if v is not None else None


def _row_to_response(row: ShipmentRow) -> ShipmentResponse:
    return ShipmentResponse(
        shipment_id=row.id,
        order_id=row.order_id,
        carrier_id=row.carrier_id,
        declared_value=str(row.declared_value),
        status=row.status,
        idempotency_key=row.idempotency_key,
        tracking_number=row.tracking_number,
        failure_reason=row.failure_reason,
        created_at=row.created_at,
        registered_at=row.registered_at,
        in_transit_at=row.in_transit_at,
        delivered_at=row.delivered_at,
        voided_at=row.voided_at,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/orders/{order_id}/shipments — create (claim-then-send)
# ---------------------------------------------------------------------------

@router.post(
    "/orders/{order_id}/shipments",
    response_model=ShipmentResponse,
    status_code=201,
    summary="Create a shipment for an Order",
    responses={
        201: {"description": "Shipment registered with carrier"},
        403: {"description": "Invalid admin secret"},
        404: {"description": "Order or carrier config not found"},
        409: {"description": "Order not in CONFIRMED status, or shipment already exists"},
        502: {"description": "Carrier gateway error"},
        503: {"description": "Admin operations not configured"},
    },
)
def create_shipment(
    order_id: str,
    body: CreateShipmentRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
) -> ShipmentResponse:
    """Register a shipment with the carrier using the claim-then-send pattern.

    declared_value defaults to order.amount if not provided (Frozen from sale).
    void_window is not part of this request — it is read live at void time.
    """
    now = datetime.now(timezone.utc)

    # Load Order
    order_row = db.execute(
        select(OrderRow).where(OrderRow.id == order_id)
    ).scalar_one_or_none()
    if order_row is None:
        raise HTTPException(status_code=404, detail="Order not found")

    # Load CarrierConfig (live read)
    carrier_repo = SQLAlchemyCarrierConfigRepository(db)
    carrier_config = carrier_repo.find_by_id(body.carrier_id)
    if carrier_config is None:
        raise HTTPException(status_code=404, detail=f"Carrier {body.carrier_id!r} not found")

    # declared_value: frozen from caller or defaulting to order.amount
    declared_value = body.declared_value if body.declared_value is not None else Decimal(str(order_row.amount))

    # Phase 1: claim PENDING (commit before network call)
    shipment_uow = SQLAlchemyShipmentUnitOfWork(db)
    order_id_typed = OrderId(order_id)

    try:
        shipment = _shipment_service.claim(
            order_id=order_id_typed,
            carrier_config=carrier_config,
            declared_value=declared_value,
            now=now,
            uow=shipment_uow,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # Phase 2: call carrier gateway
    try:
        tracking_number = _gateway.create_shipment(
            order_id=order_id_typed,
            carrier_id=carrier_config.carrier_id,
            declared_value=declared_value,
            idempotency_key=shipment.idempotency_key,
        )
    except ShipmentGatewayError as exc:
        # mark FAILED — commit the failure before re-raising
        _shipment_service.mark_failed(shipment, exc.detail, shipment_uow)
        db.commit()
        raise HTTPException(status_code=502, detail=exc.detail) from exc

    # Phase 2: mark CREATED + transition Order to SHIPPED (same commit)
    try:
        _shipment_service.mark_created(shipment, tracking_number, now, shipment_uow)
        order_uow = SQLAlchemyOrderUnitOfWork(db)
        _order_service.ship(order_id=order_id_typed, uow=order_uow, now=now)
        db.commit()
    except OrderStatusError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Return the updated row
    row = db.execute(
        select(ShipmentRow).where(ShipmentRow.order_id == order_id)
    ).scalar_one()
    return _row_to_response(row)


# ---------------------------------------------------------------------------
# GET /api/v1/orders/{order_id}/shipments
# ---------------------------------------------------------------------------

@router.get(
    "/orders/{order_id}/shipments",
    response_model=ShipmentResponse,
    status_code=200,
    summary="Get the shipment for an Order",
    responses={
        200: {"description": "Shipment found"},
        404: {"description": "No shipment for this order"},
    },
)
def get_shipment_by_order(
    order_id: str,
    db: Session = Depends(get_db),
    customer_ref: str = Depends(get_customer_ref),
    order_service: OrderService = Depends(_get_order_service),
) -> ShipmentResponse:
    """Return the shipment for an order only if the caller owns it (Law 5 — BOLA).

    Ownership is validated by OrderService.find_order_for_customer() before the
    shipment query — the domain service decides; the router only maps None → 404.

    BOLA invariant: the 404 response is identical for all rejection cases —
    non-existent order, order owned by another customer, and no shipment yet all
    return the same status and body. The caller can never enumerate resources.

    Transitional note (ADR-017 §5):
    find_shipment_for_customer() was not introduced as a ShipmentService method
    because Shipment aggregates do not carry customer_ref — that field belongs to
    Order. Adding it to ShipmentService would require cross-context access to
    OrderRepository, creating bounded-context coupling. This router-level composition
    of two existing domain primitives is the accepted transitional form until
    ADR-023 M2.x consolidates the shipping and order contexts.
    """
    # Step 1 — ownership check (domain service, Law 5)
    order_uow = SQLAlchemyOrderUnitOfWork(db)
    order = order_service.find_order_for_customer(OrderId(order_id), customer_ref, order_uow)
    if order is None:
        raise HTTPException(status_code=404, detail="No shipment found for this order")

    # Step 2 — fetch shipment (ownership already validated)
    row = db.execute(
        select(ShipmentRow).where(ShipmentRow.order_id == order_id)
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="No shipment found for this order")
    return _row_to_response(row)


# ---------------------------------------------------------------------------
# POST /api/v1/shipments/{shipment_id}/void
# ---------------------------------------------------------------------------

@router.post(
    "/shipments/{shipment_id}/void",
    response_model=ShipmentResponse,
    status_code=200,
    summary="Void a shipment within the carrier's void_window",
    responses={
        200: {"description": "Shipment voided"},
        403: {"description": "Invalid admin secret"},
        404: {"description": "Shipment not found"},
        409: {"description": "void_window expired or shipment not in CREATED status"},
        502: {"description": "Carrier gateway error"},
        503: {"description": "Admin operations not configured"},
    },
)
def void_shipment(
    shipment_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
) -> ShipmentResponse:
    """Void a CREATED shipment if within the carrier's void_window.

    void_window is read live from CarrierConfig at decision time (§13 Live).
    """
    now = datetime.now(timezone.utc)

    uow = SQLAlchemyShipmentUnitOfWork(db)
    shipment = uow.repository.find_by_id(ShipmentId(shipment_id))
    if shipment is None:
        raise HTTPException(status_code=404, detail="Shipment not found")

    carrier_repo = SQLAlchemyCarrierConfigRepository(db)
    carrier_config = carrier_repo.find_by_id(shipment.carrier_id)
    if carrier_config is None:
        raise HTTPException(status_code=404, detail=f"Carrier {shipment.carrier_id!r} not found")

    try:
        _shipment_service.void(ShipmentId(shipment_id), carrier_config, now, uow)
        db.commit()
    except ShipmentNotFoundException as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CannotVoidShipmentError as exc:
        raise HTTPException(status_code=409, detail=exc.reason) from exc
    except ShipmentGatewayError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=exc.detail) from exc

    row = db.execute(
        select(ShipmentRow).where(ShipmentRow.id == shipment_id)
    ).scalar_one()
    return _row_to_response(row)


# ---------------------------------------------------------------------------
# POST /api/v1/shipments/{shipment_id}/deliver — event-of-record
# ---------------------------------------------------------------------------

@router.post(
    "/shipments/{shipment_id}/deliver",
    response_model=ShipmentResponse,
    status_code=200,
    summary="Mark a shipment as delivered (event-of-record)",
    responses={
        200: {"description": "Shipment and Order marked DELIVERED"},
        403: {"description": "Invalid admin secret"},
        404: {"description": "Shipment not found"},
        409: {"description": "Shipment not in IN_TRANSIT status"},
        503: {"description": "Admin operations not configured"},
    },
)
def mark_delivered(
    shipment_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
) -> ShipmentResponse:
    """Mark a shipment as DELIVERED and transition Order → DELIVERED.

    This is the event-of-record path (§13): a carrier-authenticated delivery
    signal, not a cache promotion. In production, this endpoint is called by
    a signed carrier webhook handler or a confirmed carrier poll worker.

    Both Shipment and Order transitions commit atomically in one transaction.
    """
    now = datetime.now(timezone.utc)

    uow = SQLAlchemyShipmentUnitOfWork(db)
    shipment = uow.repository.find_by_id(ShipmentId(shipment_id))
    if shipment is None:
        raise HTTPException(status_code=404, detail="Shipment not found")

    try:
        _shipment_service.mark_delivered(ShipmentId(shipment_id), now, uow)
        order_uow = SQLAlchemyOrderUnitOfWork(db)
        _order_service.deliver(order_id=shipment.order_id, uow=order_uow, now=now)
        db.commit()
    except ShipmentNotFoundException as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ShipmentStatusError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OrderStatusError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    row = db.execute(
        select(ShipmentRow).where(ShipmentRow.id == shipment_id)
    ).scalar_one()
    return _row_to_response(row)
