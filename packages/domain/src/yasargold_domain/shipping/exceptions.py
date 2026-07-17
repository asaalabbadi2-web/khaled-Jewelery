"""Shipping domain exceptions.

HTTP mapping (enforced in the router, never in the domain):
    ShipmentNotFoundException  → 404
    ShipmentStatusError        → 409
    CannotVoidShipmentError    → 409 (void_window expired or wrong status)
    ShipmentGatewayError       → 502 (carrier API failure)
"""
from __future__ import annotations


class ShipmentNotFoundException(Exception):
    def __init__(self, shipment_id: str) -> None:
        self.shipment_id = shipment_id
        super().__init__(f"Shipment not found: {shipment_id}")


class ShipmentStatusError(Exception):
    def __init__(
        self,
        shipment_id: str,
        *,
        current_status: str,
        expected: str,
    ) -> None:
        self.shipment_id = shipment_id
        self.current_status = current_status
        self.expected = expected
        super().__init__(
            f"Shipment {shipment_id} is {current_status!r}, expected {expected!r}"
        )


class CannotVoidShipmentError(Exception):
    """Raised when void_window has expired or shipment is not in CREATED status."""

    def __init__(self, shipment_id: str, reason: str) -> None:
        self.shipment_id = shipment_id
        self.reason = reason
        super().__init__(f"Cannot void shipment {shipment_id}: {reason}")


class ShipmentGatewayError(Exception):
    """Carrier API returned an error during create or void."""

    def __init__(self, carrier_id: str, detail: str) -> None:
        self.carrier_id = carrier_id
        self.detail = detail
        super().__init__(f"Carrier {carrier_id!r} gateway error: {detail}")
