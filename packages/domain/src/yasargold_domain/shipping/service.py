"""ShipmentService — claim-then-send lifecycle for Shipment aggregates.

claim-then-send is MANDATORY here from day one (not deferred like in Notifications).
A carrier registration is a billable, irreversible external action — duplicate labels
cost money and confuse customers. The pattern:

    Phase 1 — claim():
        Save PENDING Shipment with idempotency_key.
        Caller commits before the network call.

    Phase 2 — mark_created() or mark_failed():
        Update PENDING → CREATED (with tracking_number) or PENDING → FAILED.
        Caller commits.

Crash recovery:
    If process crashes after carrier ACKs but before mark_created() commits:
    On retry, find existing PENDING row, call carrier with same idempotency_key
    → carrier deduplicates → returns same tracking_number → mark_created() succeeds.

ADR-015: all datetime parameters are injected (Clock Protocol).
§13: declared_value is Frozen (passed in, never recomputed); void_window is Live
     (read from CarrierConfig by caller and passed to can_void()).
"""
from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timezone

from yasargold_domain.shipping.carrier_config import CarrierConfig
from yasargold_domain.shipping.events import ShipmentCreated, ShipmentDelivered, ShipmentVoided
from yasargold_domain.shipping.exceptions import (
    CannotVoidShipmentError,
    ShipmentGatewayError,
    ShipmentNotFoundException,
    ShipmentStatusError,
)
from yasargold_domain.shipping.gateway import ShippingGateway
from yasargold_domain.shipping.repository import ShipmentUnitOfWork
from yasargold_domain.shipping.shipment import Shipment, ShipmentStatus
from yasargold_domain.shared.identifiers import OrderId, ShipmentId

from decimal import Decimal


def _new_shipment_id() -> ShipmentId:
    return ShipmentId(f"shp_{uuid.uuid4().hex[:16]}")


class ShipmentService:
    """Creates and transitions Shipment aggregates.

    Stateless — safe to instantiate once at application startup.
    """

    def __init__(self, gateway: ShippingGateway) -> None:
        self._gateway = gateway

    def claim(
        self,
        order_id: OrderId,
        carrier_config: CarrierConfig,
        declared_value: Decimal,
        now: datetime,
        uow: ShipmentUnitOfWork,
    ) -> Shipment:
        """Phase 1: save a PENDING Shipment.

        Caller MUST commit before calling the carrier gateway.
        The committed PENDING row is the observable state if the process crashes
        between the network send and the subsequent mark_created() commit.

        declared_value is Frozen: must be computed by the caller from
        locked_rate_per_gram_24k × weight at sale time — never from current gold price.
        """
        idempotency_key = f"{order_id}:SHIPMENT"
        shipment = Shipment(
            id=_new_shipment_id(),
            order_id=order_id,
            carrier_id=carrier_config.carrier_id,
            declared_value=declared_value,
            status=ShipmentStatus.PENDING,
            idempotency_key=idempotency_key,
            created_at=now,
        )
        uow.repository.save(shipment)
        return shipment

    def mark_created(
        self,
        shipment: Shipment,
        tracking_number: str,
        now: datetime,
        uow: ShipmentUnitOfWork,
    ) -> Shipment:
        """Phase 2 (success path): PENDING → CREATED with tracking_number.

        Caller commits after this returns.
        Emits ShipmentCreated to the Outbox.
        """
        if not shipment.can_register():
            raise ShipmentStatusError(
                str(shipment.id),
                current_status=shipment.status.value,
                expected="PENDING",
            )
        result = replace(
            shipment,
            status=ShipmentStatus.CREATED,
            tracking_number=tracking_number,
            registered_at=now,
        )
        uow.repository.save(result)
        uow.outbox.enqueue(
            ShipmentCreated(
                shipment_id=result.id,
                order_id=result.order_id,
                carrier_id=result.carrier_id,
                tracking_number=tracking_number,
                declared_value=result.declared_value,
                created_at=now,
            )
        )
        return result

    def mark_failed(
        self,
        shipment: Shipment,
        reason: str,
        uow: ShipmentUnitOfWork,
    ) -> Shipment:
        """Phase 2 (failure path): PENDING → FAILED.

        Caller commits after this returns.
        """
        if not shipment.can_register():
            raise ShipmentStatusError(
                str(shipment.id),
                current_status=shipment.status.value,
                expected="PENDING",
            )
        result = replace(shipment, status=ShipmentStatus.FAILED, failure_reason=reason)
        uow.repository.save(result)
        return result

    def void(
        self,
        shipment_id: ShipmentId,
        carrier_config: CarrierConfig,
        now: datetime,
        uow: ShipmentUnitOfWork,
    ) -> Shipment:
        """Void a CREATED shipment within the carrier's void_window.

        carrier_config is loaded live by the caller — void_window is Live (§13).
        can_void(now, void_window) is a pure function on the aggregate.

        Calls gateway.void_shipment() before marking VOIDED. If the carrier
        rejects the void, ShipmentGatewayError propagates to the caller.
        """
        shipment = uow.repository.find_by_id(shipment_id)
        if shipment is None:
            raise ShipmentNotFoundException(str(shipment_id))
        if not shipment.can_void(now, carrier_config.void_window):
            raise CannotVoidShipmentError(
                str(shipment_id),
                reason=(
                    f"status={shipment.status.value!r} or void_window "
                    f"of {carrier_config.void_window} has expired"
                ),
            )
        self._gateway.void_shipment(shipment.carrier_id, shipment.tracking_number or "")
        result = replace(shipment, status=ShipmentStatus.VOIDED, voided_at=now)
        uow.repository.save(result)
        uow.outbox.enqueue(
            ShipmentVoided(
                shipment_id=result.id,
                order_id=result.order_id,
                voided_at=now,
            )
        )
        return result

    def mark_in_transit(
        self,
        shipment_id: ShipmentId,
        now: datetime,
        uow: ShipmentUnitOfWork,
    ) -> Shipment:
        """CREATED → IN_TRANSIT (carrier picked up).

        Triggered by carrier webhook or tracking poll. Caller commits.
        """
        shipment = uow.repository.find_by_id(shipment_id)
        if shipment is None:
            raise ShipmentNotFoundException(str(shipment_id))
        if not shipment.can_mark_in_transit():
            raise ShipmentStatusError(
                str(shipment_id),
                current_status=shipment.status.value,
                expected="CREATED",
            )
        result = replace(shipment, status=ShipmentStatus.IN_TRANSIT, in_transit_at=now)
        uow.repository.save(result)
        return result

    def mark_delivered(
        self,
        shipment_id: ShipmentId,
        now: datetime,
        uow: ShipmentUnitOfWork,
    ) -> Shipment:
        """IN_TRANSIT → DELIVERED — event-of-record.

        Source: carrier-authenticated webhook or confirmed carrier poll.
        Emits ShipmentDelivered to the Outbox. A worker consumes this event
        to transition Order → DELIVERED (§13: two separate paths for same info).

        Caller commits after this returns.
        """
        shipment = uow.repository.find_by_id(shipment_id)
        if shipment is None:
            raise ShipmentNotFoundException(str(shipment_id))
        if not shipment.can_deliver():
            raise ShipmentStatusError(
                str(shipment_id),
                current_status=shipment.status.value,
                expected="IN_TRANSIT",
            )
        result = replace(shipment, status=ShipmentStatus.DELIVERED, delivered_at=now)
        uow.repository.save(result)
        uow.outbox.enqueue(
            ShipmentDelivered(
                shipment_id=result.id,
                order_id=result.order_id,
                delivered_at=now,
            )
        )
        return result
