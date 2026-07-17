"""SQLAlchemy implementations of ShipmentRepository and CarrierConfigRepository."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from yasargold_domain.shipping.carrier_config import CarrierConfig
from yasargold_domain.shipping.events import ShipmentCreated, ShipmentDelivered, ShipmentVoided
from yasargold_domain.shipping.shipment import Shipment, ShipmentStatus
from yasargold_domain.shared.identifiers import OrderId, ShipmentId

from yasargold_commerce.infra.shipment_orm import CarrierConfigRow, ShipmentRow
from yasargold_commerce.infra.reservation_orm import OutboxEventRow


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SQLAlchemyShipmentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, shipment: Shipment) -> None:
        existing = self._session.get(ShipmentRow, str(shipment.id))
        if existing is None:
            self._session.add(ShipmentRow(
                id=str(shipment.id),
                order_id=str(shipment.order_id),
                carrier_id=shipment.carrier_id,
                declared_value=str(shipment.declared_value),
                status=shipment.status.value,
                idempotency_key=shipment.idempotency_key,
                tracking_number=shipment.tracking_number,
                failure_reason=shipment.failure_reason,
                created_at=shipment.created_at,
                registered_at=shipment.registered_at,
                in_transit_at=shipment.in_transit_at,
                delivered_at=shipment.delivered_at,
                voided_at=shipment.voided_at,
            ))
        else:
            existing.status = shipment.status.value
            existing.tracking_number = shipment.tracking_number
            existing.failure_reason = shipment.failure_reason
            existing.registered_at = shipment.registered_at
            existing.in_transit_at = shipment.in_transit_at
            existing.delivered_at = shipment.delivered_at
            existing.voided_at = shipment.voided_at

    def find_by_id(self, shipment_id: ShipmentId) -> Shipment | None:
        row = self._session.get(ShipmentRow, str(shipment_id))
        return self._row_to_domain(row) if row else None

    def find_by_order_id(self, order_id: OrderId) -> Shipment | None:
        row = self._session.execute(
            select(ShipmentRow).where(ShipmentRow.order_id == str(order_id))
        ).scalar_one_or_none()
        return self._row_to_domain(row) if row else None

    def _row_to_domain(self, row: ShipmentRow) -> Shipment:
        return Shipment(
            id=ShipmentId(row.id),
            order_id=OrderId(row.order_id),
            carrier_id=row.carrier_id,
            declared_value=Decimal(str(row.declared_value)),
            status=ShipmentStatus(row.status),
            idempotency_key=row.idempotency_key,
            tracking_number=row.tracking_number,
            failure_reason=row.failure_reason,
            created_at=row.created_at,
            registered_at=row.registered_at,
            in_transit_at=row.in_transit_at,
            delivered_at=row.delivered_at,
            voided_at=row.voided_at,
        )


class SQLAlchemyCarrierConfigRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def find_by_id(self, carrier_id: str) -> CarrierConfig | None:
        from datetime import timedelta
        row = self._session.get(CarrierConfigRow, carrier_id)
        if row is None:
            return None
        return CarrierConfig(
            carrier_id=row.carrier_id,
            name=row.name,
            void_window=timedelta(seconds=row.void_window_seconds),
        )


class SQLAlchemyShipmentOutbox:
    """Persists shipping events to the shared outbox_events table."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def enqueue(
        self,
        event: ShipmentCreated | ShipmentDelivered | ShipmentVoided,
    ) -> None:
        payload: dict = {}
        event_type = type(event).__name__

        if isinstance(event, ShipmentCreated):
            payload = {
                "shipment_id": str(event.shipment_id),
                "order_id": str(event.order_id),
                "carrier_id": event.carrier_id,
                "tracking_number": event.tracking_number,
                "declared_value": str(event.declared_value),
            }
        elif isinstance(event, ShipmentDelivered):
            payload = {
                "shipment_id": str(event.shipment_id),
                "order_id": str(event.order_id),
                "delivered_at": event.delivered_at.isoformat(),
            }
        elif isinstance(event, ShipmentVoided):
            payload = {
                "shipment_id": str(event.shipment_id),
                "order_id": str(event.order_id),
                "voided_at": event.voided_at.isoformat(),
            }

        self._session.add(OutboxEventRow(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            payload=json.dumps(payload),
            created_at=_utcnow(),
        ))
