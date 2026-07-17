"""FakeCarrierGateway — in-memory stub for domain tests.

ADR-019: Every Protocol must have a Fake in {capability}/testing.py.

Usage:
    from yasargold_domain.shipping.testing import FakeCarrierGateway

    gw = FakeCarrierGateway()
    service = ShipmentService(gw)
    ...
    assert gw.create_count == 1
    assert gw.last_tracking_number == "FAKE-TRK-001"

Forced failures:
    gw = FakeCarrierGateway(fail_create_on_next=True)
    # next create_shipment() raises ShipmentGatewayError
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from yasargold_domain.shared.identifiers import OrderId
from yasargold_domain.shipping.exceptions import ShipmentGatewayError


@dataclass
class FakeCarrierGateway:
    """In-memory ShippingGateway. Records all calls. Never contacts a carrier.

    Attributes:
        fail_create_on_next: If True, the next create_shipment() raises ShipmentGatewayError
                             and the flag self-clears.
        fail_void_on_next:   If True, the next void_shipment() raises ShipmentGatewayError
                             and the flag self-clears.
        created:             List of dicts recording each create_shipment() call.
        voided:              List of tracking_number strings from each void_shipment() call.
        next_tracking:       Tracking number returned by the next create_shipment() call.
    """

    fail_create_on_next: bool = False
    fail_void_on_next: bool = False
    created: list[dict] = field(default_factory=list)
    voided: list[str] = field(default_factory=list)
    next_tracking: str = "FAKE-TRK-001"

    def create_shipment(
        self,
        order_id: OrderId,
        carrier_id: str,
        declared_value: Decimal,
        idempotency_key: str,
    ) -> str:
        if self.fail_create_on_next:
            self.fail_create_on_next = False
            raise ShipmentGatewayError(carrier_id, "FakeCarrierGateway: simulated create failure")
        tracking = self.next_tracking
        self.created.append(
            {
                "order_id": order_id,
                "carrier_id": carrier_id,
                "declared_value": declared_value,
                "idempotency_key": idempotency_key,
                "tracking_number": tracking,
            }
        )
        return tracking

    def void_shipment(self, carrier_id: str, tracking_number: str) -> None:
        if self.fail_void_on_next:
            self.fail_void_on_next = False
            raise ShipmentGatewayError(carrier_id, "FakeCarrierGateway: simulated void failure")
        self.voided.append(tracking_number)

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    @property
    def create_count(self) -> int:
        return len(self.created)

    @property
    def void_count(self) -> int:
        return len(self.voided)

    @property
    def last_tracking_number(self) -> str | None:
        return self.created[-1]["tracking_number"] if self.created else None
