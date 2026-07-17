"""Repository and UnitOfWork Protocols for the Shipping bounded context."""
from __future__ import annotations

from typing import Protocol

from yasargold_domain.shipping.carrier_config import CarrierConfig
from yasargold_domain.shipping.events import ShipmentCreated, ShipmentDelivered, ShipmentVoided
from yasargold_domain.shipping.shipment import Shipment
from yasargold_domain.shared.identifiers import OrderId, ShipmentId


class ShipmentRepository(Protocol):
    def save(self, shipment: Shipment) -> None: ...
    def find_by_id(self, shipment_id: ShipmentId) -> Shipment | None: ...
    def find_by_order_id(self, order_id: OrderId) -> Shipment | None: ...


class CarrierConfigRepository(Protocol):
    def find_by_id(self, carrier_id: str) -> CarrierConfig | None: ...


class ShipmentEventOutbox(Protocol):
    def enqueue(
        self,
        event: ShipmentCreated | ShipmentDelivered | ShipmentVoided,
    ) -> None: ...


class ShipmentUnitOfWork(Protocol):
    repository: ShipmentRepository
    outbox: ShipmentEventOutbox

    def __enter__(self) -> ShipmentUnitOfWork: ...
    def __exit__(self, *args: object) -> None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
