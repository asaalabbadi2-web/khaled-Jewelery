"""ShippingGateway Protocol — provider-agnostic carrier registration interface.

Implementations live in apps/commerce-api/infra/:
    LogShippingGateway  — dev / test: logs only, returns stub tracking number
    SamaraGateway       — Sprint 7+: Aramex / SMSA / DHL

The domain never imports a carrier SDK (ADR-009).

Idempotency:
    create_shipment() receives an idempotency_key (f"{order_id}:SHIPMENT").
    Carriers that support idempotency (Aramex, SMSA) deduplicate on their side,
    preventing double-label creation if the process crashes after the carrier ACKs
    but before mark_created() commits.
    This is the closure for the claim-then-send atomicity gap (ADR-015 §Atomicity).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from yasargold_domain.shared.identifiers import OrderId


class ShippingGateway(Protocol):
    """Register and manage shipments with a carrier.

    Returns:
        create_shipment → tracking_number: opaque string for display and void
        void_shipment   → None (raises on failure)

    Raises:
        ShipmentGatewayError: any failure from the carrier API.
            The caller (ShipmentService) catches this and records FAILED.
    """

    def create_shipment(
        self,
        order_id: OrderId,
        carrier_id: str,
        declared_value: Decimal,
        idempotency_key: str,
    ) -> str:
        """Register a shipment with the carrier and return the tracking number.

        Args:
            order_id:          The order being shipped (for carrier reference).
            carrier_id:        Which carrier to use.
            declared_value:    Insurance value — FROZEN from locked_rate×weight at sale time.
                               Must NOT be recomputed from current gold price.
            idempotency_key:   f"{order_id}:SHIPMENT" — stable across retries.
        """
        ...

    def void_shipment(
        self,
        carrier_id: str,
        tracking_number: str,
    ) -> None:
        """Cancel a registered shipment with the carrier.

        Raises ShipmentGatewayError if the carrier rejects the void
        (e.g., void_window already expired on the carrier's side).
        """
        ...
