"""Shipping domain events.

ShipmentCreated — published when a shipment is registered with the carrier.
    Consumers: ERP (update item to IN_TRANSIT), Analytics, Notification worker.

ShipmentDelivered — event-of-record for delivery.
    Source: signed carrier webhook or confirmed carrier poll via Outbox.
    IMPORTANT: this is NOT a cache promotion — the delivery event must come
    from a carrier-authenticated source (signed webhook or poll with idempotency).
    Consumer: OrderWorker transitions Order → DELIVERED using this event.
    This is the only path for Order.status = DELIVERED (§13: two separate paths).

ShipmentVoided — published when a shipment is cancelled within void_window.
    Consumers: Notification worker (send cancellation SMS), ERP.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from yasargold_domain.reservation.events import DomainEvent, _new_event_id, _utcnow
from yasargold_domain.shared.identifiers import OrderId, ShipmentId


@dataclass(frozen=True)
class ShipmentCreated(DomainEvent):
    """A shipment was successfully registered with the carrier."""
    shipment_id: ShipmentId = field(default=ShipmentId(""))
    order_id: OrderId = field(default=OrderId(""))
    carrier_id: str = field(default="")
    tracking_number: str = field(default="")
    declared_value: Decimal = field(default=Decimal("0"))
    created_at: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True)
class ShipmentDelivered(DomainEvent):
    """A shipment was delivered — event-of-record (not cache promotion).

    This event is the authoritative signal for Order → DELIVERED transition.
    Source: carrier-authenticated webhook or confirmed carrier poll.
    """
    shipment_id: ShipmentId = field(default=ShipmentId(""))
    order_id: OrderId = field(default=OrderId(""))
    delivered_at: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True)
class ShipmentVoided(DomainEvent):
    """A shipment was voided within the carrier's void_window."""
    shipment_id: ShipmentId = field(default=ShipmentId(""))
    order_id: OrderId = field(default=OrderId(""))
    voided_at: datetime = field(default_factory=_utcnow)
