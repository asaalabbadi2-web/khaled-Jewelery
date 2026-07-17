"""Shipment aggregate — tracks a physical shipment for one Order.

One Shipment per Order (enforced by UniqueConstraint on order_id in the ORM).

State machine:
    PENDING    → CREATED    (carrier registered, has tracking_number)
    CREATED    → IN_TRANSIT (carrier picked up)
    CREATED    → VOIDED     (cancelled within void_window from registered_at)
    IN_TRANSIT → DELIVERED  (event-of-record: signed webhook or confirmed poll)
    PENDING    → FAILED     (carrier rejected registration)

All mutations return a new Shipment (frozen dataclass — value-object style).

Key invariants:
    - declared_value is Frozen: set at claim time, never updated (§13)
    - carrier_id is stored from the moment of claim, not re-read on void
    - can_void(now, void_window) takes both arguments externally — pure function
      (void_window is Live, read from CarrierConfig by the caller; now is injected
      per ADR-015 Clock Protocol)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum

from yasargold_domain.shared.identifiers import OrderId, ShipmentId


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ShipmentStatus(str, Enum):
    PENDING    = "PENDING"
    CREATED    = "CREATED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED  = "DELIVERED"
    VOIDED     = "VOIDED"
    FAILED     = "FAILED"

    @property
    def is_terminal(self) -> bool:
        return self in (
            ShipmentStatus.DELIVERED,
            ShipmentStatus.VOIDED,
            ShipmentStatus.FAILED,
        )


@dataclass(frozen=True)
class Shipment:
    """Immutable snapshot of a Shipment at a point in time.

    All mutations return a new Shipment instance via dataclasses.replace().
    """
    id: ShipmentId
    order_id: OrderId
    carrier_id: str
    declared_value: Decimal
    status: ShipmentStatus
    idempotency_key: str
    created_at: datetime = field(default_factory=_utcnow)
    tracking_number: str | None = None
    registered_at: datetime | None = None
    in_transit_at: datetime | None = None
    delivered_at: datetime | None = None
    voided_at: datetime | None = None
    failure_reason: str | None = None

    # ------------------------------------------------------------------
    # Guard predicates
    # ------------------------------------------------------------------

    def can_void(self, now: datetime, void_window: timedelta) -> bool:
        """Return True iff this shipment can be voided right now.

        Pure function: both `now` and `void_window` are injected by the caller.
        - `now` injected per ADR-015 (Clock Protocol) — enables time-travel in tests
        - `void_window` read live from CarrierConfig (§13 Live) — carrier's policy applies immediately

        Only CREATED shipments can be voided; void_window is measured from registered_at.
        """
        return (
            self.status == ShipmentStatus.CREATED
            and self.registered_at is not None
            and now < self.registered_at + void_window
        )

    def can_register(self) -> bool:
        return self.status == ShipmentStatus.PENDING

    def can_mark_in_transit(self) -> bool:
        return self.status == ShipmentStatus.CREATED

    def can_deliver(self) -> bool:
        return self.status == ShipmentStatus.IN_TRANSIT

    @property
    def is_terminal(self) -> bool:
        return self.status.is_terminal
