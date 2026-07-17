"""Reservation policies — external conditions that govern whether a Quote
may be converted to a Reservation.

Separation of concerns:
    Quote.can_reserve(now)       → quote is internally valid (status + time)
    ReservationPolicy.check(...) → external context allows reservation

Policy ordering principle (cheap → expensive):
    1. DefaultQuotePolicy      — pure in-memory, no I/O
    2. TradingHaltPolicy       — reads Settings cache (cheap read)
    3. ItemAvailabilityPolicy  — queries inventory DB (one SELECT)
    4. CustomerEligibilityPolicy / FraudPolicy — external services (expensive)

CompositePolicy short-circuits at the first denial, so ordering matters
under load. Implement policies from cheapest to most expensive.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol

from yasargold_domain.pricing.quotes import Quote


class ReservationRejectionReason(str, Enum):
    """Typed reason for a policy denial.

    Values become API error codes and audit log entries — keep them stable.
    Adding new values is non-breaking; renaming is a breaking change.
    """
    QUOTE_EXPIRED          = "QUOTE_EXPIRED"
    QUOTE_STATUS_INVALID   = "QUOTE_STATUS_INVALID"
    ITEM_UNAVAILABLE       = "ITEM_UNAVAILABLE"
    ITEM_ALREADY_RESERVED  = "ITEM_ALREADY_RESERVED"
    TRADING_HALTED         = "TRADING_HALTED"
    CUSTOMER_INELIGIBLE    = "CUSTOMER_INELIGIBLE"
    DAILY_LIMIT_EXCEEDED   = "DAILY_LIMIT_EXCEEDED"
    FRAUD_SUSPECTED        = "FRAUD_SUSPECTED"


@dataclass(frozen=True)
class PolicyResult:
    """Outcome of a single policy check.

    allowed:         True if the reservation may proceed through this policy.
    rejection_reason: Typed reason when denied — used by API error responses
                      and audit logs. None when allowed.
    policy:          Name of the policy (for composite audit trails).
    """
    allowed: bool
    rejection_reason: ReservationRejectionReason | None = None
    policy: str = "unknown"

    @classmethod
    def permit(cls, policy: str) -> PolicyResult:
        return cls(allowed=True, policy=policy)

    @classmethod
    def deny(cls, reason: ReservationRejectionReason, policy: str) -> PolicyResult:
        return cls(allowed=False, rejection_reason=reason, policy=policy)


class ReservationPolicy(Protocol):
    """Interface for any reservation pre-condition check.

    Implementors receive the Quote and contextual information, and return
    a PolicyResult. Must be stateless or carry read-only dependencies only.

    Ordering contract: implement checks cheapest-first so CompositePolicy
    can short-circuit before any expensive I/O.
    """

    def check(self, quote: Quote, item_id: int, now: datetime) -> PolicyResult:
        ...


@dataclass
class DefaultQuotePolicy:
    """Cheapest policy: checks that the Quote itself is internally valid.

    This is the mandatory first policy. If Quote.can_reserve(now) is False,
    no further checks are needed.
    """
    _name: str = field(default="DefaultQuotePolicy", init=False)

    def check(self, quote: Quote, item_id: int, now: datetime) -> PolicyResult:
        if not quote.can_reserve(now):
            if quote.is_expired(now):
                return PolicyResult.deny(
                    reason=ReservationRejectionReason.QUOTE_EXPIRED,
                    policy=self._name,
                )
            return PolicyResult.deny(
                reason=ReservationRejectionReason.QUOTE_STATUS_INVALID,
                policy=self._name,
            )
        return PolicyResult.permit(policy=self._name)


@dataclass
class CompositePolicy:
    """Evaluates policies in order; stops at the first denial.

    Ordering: cheapest checks first. The result carries the name and typed
    reason from whichever policy caused the denial.
    """
    policies: list[ReservationPolicy]
    _name: str = field(default="CompositePolicy", init=False)

    def check(self, quote: Quote, item_id: int, now: datetime) -> PolicyResult:
        for policy in self.policies:
            result = policy.check(quote, item_id, now)
            if not result.allowed:
                return result
        return PolicyResult.permit(policy=self._name)


# ---------------------------------------------------------------------------
# Stubs — skeleton policies ready for Sprint 3 implementation
# ---------------------------------------------------------------------------

@dataclass
class ItemAvailabilityPolicy:
    """Rejects if the item is already reserved or out of stock.

    Sprint 3: inject an InventoryReservationRepository.
    """
    _name: str = field(default="ItemAvailabilityPolicy", init=False)

    def check(self, quote: Quote, item_id: int, now: datetime) -> PolicyResult:
        raise NotImplementedError("ItemAvailabilityPolicy requires Sprint 3 inventory repo")


@dataclass
class TradingHaltPolicy:
    """Rejects if a system-wide trading halt is active.

    Sprint 3: inject a settings repository. Cheaper than DB — reads a cache.
    """
    _name: str = field(default="TradingHaltPolicy", init=False)

    def check(self, quote: Quote, item_id: int, now: datetime) -> PolicyResult:
        raise NotImplementedError("TradingHaltPolicy requires Sprint 3 settings repo")
