"""Quote domain model — lifecycle and state of a pricing quote.

A Quote is the unit of commitment between the customer and the store:
it captures which gold price was used, when it expires, and whether
it can be used to open a Reservation.

State machine:
    FRESH  ──── [90s elapsed] ──▶  STALE
    FRESH  ──── [POST /reservations] ──▶  LOCKED
    STALE  ──── [5min elapsed] ──▶  HALTED
    LOCKED ──── [window elapsed] ──▶  EXPIRED
    LOCKED ──── [cancelled] ──▶  INVALID
    HALTED / EXPIRED / INVALID  — terminal, no transitions out

Validity check rule (ADR-006):
    Status is necessary but not sufficient for allowing a reservation.
    A Quote with status=FRESH but valid_until in the past is expired in fact.
    Use Quote.can_reserve(now) — never quote.status.allows_reservation alone.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from yasargold_domain.shared.identifiers import ItemId, QuoteId

__all__ = ["QuoteId", "QuoteStatus", "Quote"]


class QuoteStatus(str, Enum):
    """Lifecycle states of a pricing quote.

    | Status  | Meaning                                    | allows_reservation |
    |---------|--------------------------------------------|-------------------|
    | FRESH   | Rate < 90 s old — fully valid              | ✅                 |
    | STALE   | Rate 90 s–5 min — browsing OK, no lock     | ❌                 |
    | HALTED  | Rate > 5 min stale or source unreachable   | ❌ (snapshot=null) |
    | LOCKED  | Rate frozen inside an active Reservation   | ✅ same quote only  |
    | EXPIRED | Reservation window elapsed                 | ❌                 |
    | INVALID | quote_id unknown or cancelled              | ❌                 |
    """
    FRESH   = "FRESH"
    STALE   = "STALE"
    HALTED  = "HALTED"
    LOCKED  = "LOCKED"
    EXPIRED = "EXPIRED"
    INVALID = "INVALID"

    @property
    def allows_reservation(self) -> bool:
        """Status-only gate. Prefer Quote.can_reserve(now) for real checks."""
        return self in (QuoteStatus.FRESH, QuoteStatus.LOCKED)

    @property
    def is_terminal(self) -> bool:
        """No further transitions are possible from this status."""
        return self in (QuoteStatus.HALTED, QuoteStatus.EXPIRED, QuoteStatus.INVALID)

    @property
    def requires_quote_id(self) -> bool:
        """A quote_id must be present for this status to be meaningful."""
        return self in (QuoteStatus.LOCKED, QuoteStatus.EXPIRED, QuoteStatus.INVALID)


@dataclass(frozen=True)
class Quote:
    """Immutable Aggregate capturing a single pricing commitment.

    Transition rules:
    - Created by the read path with status=FRESH or STALE (no id yet).
    - Reservation Engine transitions FRESH → LOCKED and assigns id.
    - Never mutated in place: transitions produce new Quote instances.

    Time fields:
    - issued_at:  when this Quote object was generated.
    - valid_from: earliest moment the Quote can be used (usually == issued_at,
                  but separated so queued or pre-issued quotes work correctly).
    - valid_until: hard expiry — once elapsed, can_reserve() returns False
                   regardless of status.

    Audit fields:
    - gold_price_id: FK to the GoldPrice row — answers "why was it X SAR?"
    - pricing_engine_version: which formula was used — answers "how was it computed?"
    """
    status: QuoteStatus
    gold_price_id: int
    gold_rate_per_gram_24k: Decimal
    karat_rate_per_gram: Decimal
    issued_at: datetime
    valid_from: datetime
    valid_until: datetime
    pricing_engine_version: str
    id: QuoteId | None = None
    item_id: ItemId | None = None

    # ------------------------------------------------------------------
    # Behaviour — always pass `now` explicitly for testability
    # ------------------------------------------------------------------

    def is_expired(self, now: datetime | None = None) -> bool:
        """True if valid_until has elapsed, regardless of status."""
        t = now or datetime.now(timezone.utc)
        return t >= self.valid_until.replace(tzinfo=timezone.utc)

    def is_valid(self, now: datetime | None = None) -> bool:
        """True if the Quote is still within its window and not in a terminal state."""
        return not self.is_expired(now) and not self.status.is_terminal

    def can_reserve(self, now: datetime | None = None) -> bool:
        """True if this Quote may be used to open or continue a Reservation.

        Both conditions must hold:
          1. status.allows_reservation (FRESH or LOCKED)
          2. valid_until has not elapsed
        """
        return self.status.allows_reservation and not self.is_expired(now)

    def can_checkout(self, now: datetime | None = None) -> bool:
        """True if a LOCKED Quote is still within its reservation window."""
        return self.status == QuoteStatus.LOCKED and not self.is_expired(now)
