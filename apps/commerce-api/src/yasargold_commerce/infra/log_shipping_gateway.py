"""LogShippingGateway — dev / test stub.

Returns a deterministic stub tracking number.
Never makes a network call.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from yasargold_domain.shared.identifiers import OrderId

log = logging.getLogger(__name__)

_STUB_TRACKING_PREFIX = "STUB-TRK-"


class LogShippingGateway:
    """Logs shipment operations instead of calling a carrier API.

    create_shipment returns a deterministic tracking number based on order_id.
    void_shipment logs and returns None.
    """

    def create_shipment(
        self,
        order_id: OrderId,
        carrier_id: str,
        declared_value: Decimal,
        idempotency_key: str,
    ) -> str:
        tracking_number = f"{_STUB_TRACKING_PREFIX}{order_id}"
        log.info(
            "log_shipping_gateway: create_shipment carrier=%s order=%s "
            "declared_value=%s idempotency_key=%s → tracking=%s",
            carrier_id, order_id, declared_value, idempotency_key, tracking_number,
        )
        return tracking_number

    def void_shipment(
        self,
        carrier_id: str,
        tracking_number: str,
    ) -> None:
        log.info(
            "log_shipping_gateway: void_shipment carrier=%s tracking=%s",
            carrier_id, tracking_number,
        )
