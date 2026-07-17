"""CarrierConfig — live configuration read from DB at decision time.

void_window is the canonical example of a Live value (§13): the carrier's policy
governs whether a void request will be accepted, so we read it from CarrierConfig
at the moment the void decision is made — never snapshot it onto the Shipment.

If Aramex changes their void_window from 6h to 4h, every new void decision
immediately respects the new policy without any data migration.

Contrast with declared_value, which is Frozen: set once at claim time from
locked_rate × weight, and must not change even if the gold price moves.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True)
class CarrierConfig:
    """Immutable snapshot of carrier configuration for a single decision.

    Loaded fresh from DB each time a void or create decision is made.
    Never cached on the Shipment aggregate.
    """
    carrier_id: str
    name: str
    void_window: timedelta
