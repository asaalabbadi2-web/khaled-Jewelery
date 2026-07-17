"""Unit tests for ReservationPolicy, CompositePolicy, and PolicyResult.

Zero infrastructure — no DB, no HTTP. All tests run against plain domain objects.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from yasargold_domain.pricing.quotes import Quote, QuoteId, QuoteStatus
from yasargold_domain.pricing.reservation_policy import (
    CompositePolicy,
    DefaultQuotePolicy,
    PolicyResult,
    ReservationRejectionReason,
)

_NOW = datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc)
_ITEM_ID = 42


def _make_quote(
    status: QuoteStatus = QuoteStatus.FRESH,
    valid_until_offset: timedelta = timedelta(seconds=90),
    id: QuoteId | None = None,
) -> Quote:
    issued = _NOW
    return Quote(
        status=status,
        gold_price_id=1,
        gold_rate_per_gram_24k=Decimal("230.00"),
        karat_rate_per_gram=Decimal("201.25"),
        issued_at=issued,
        valid_from=issued,
        valid_until=issued + valid_until_offset,
        pricing_engine_version="v1",
        id=id,
        item_id=_ITEM_ID,
    )


# ---------------------------------------------------------------------------
# PolicyResult
# ---------------------------------------------------------------------------

class TestPolicyResult:
    def test_permit_is_allowed(self):
        r = PolicyResult.permit(policy="test")
        assert r.allowed is True
        assert r.rejection_reason is None

    def test_deny_is_not_allowed(self):
        r = PolicyResult.deny(
            reason=ReservationRejectionReason.ITEM_UNAVAILABLE,
            policy="test",
        )
        assert r.allowed is False
        assert r.rejection_reason == ReservationRejectionReason.ITEM_UNAVAILABLE

    def test_denial_reason_is_typed_enum(self):
        r = PolicyResult.deny(
            reason=ReservationRejectionReason.TRADING_HALTED,
            policy="test",
        )
        assert isinstance(r.rejection_reason, ReservationRejectionReason)

    def test_denial_reason_serialises_to_string(self):
        """Enum values must be stable strings — used as API error codes."""
        assert ReservationRejectionReason.QUOTE_EXPIRED.value == "QUOTE_EXPIRED"
        assert ReservationRejectionReason.ITEM_UNAVAILABLE.value == "ITEM_UNAVAILABLE"
        assert ReservationRejectionReason.TRADING_HALTED.value == "TRADING_HALTED"

    def test_result_is_frozen(self):
        r = PolicyResult.permit(policy="test")
        with pytest.raises((AttributeError, TypeError)):
            r.allowed = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# DefaultQuotePolicy
# ---------------------------------------------------------------------------

class TestDefaultQuotePolicy:
    def setup_method(self):
        self.policy = DefaultQuotePolicy()

    def test_permits_fresh_within_window(self):
        q = _make_quote(QuoteStatus.FRESH, timedelta(seconds=90))
        result = self.policy.check(q, _ITEM_ID, _NOW + timedelta(seconds=30))
        assert result.allowed is True

    def test_permits_locked_within_window(self):
        q = _make_quote(QuoteStatus.LOCKED, timedelta(minutes=10), id=QuoteId("qt_abc"))
        result = self.policy.check(q, _ITEM_ID, _NOW + timedelta(minutes=5))
        assert result.allowed is True

    def test_denies_fresh_after_window_with_expired_reason(self):
        """Expired quote → QUOTE_EXPIRED, not QUOTE_STATUS_INVALID."""
        q = _make_quote(QuoteStatus.FRESH, timedelta(seconds=90))
        result = self.policy.check(q, _ITEM_ID, _NOW + timedelta(seconds=91))
        assert result.allowed is False
        assert result.rejection_reason == ReservationRejectionReason.QUOTE_EXPIRED

    def test_denies_stale_with_status_invalid_reason(self):
        """STALE status within window → QUOTE_STATUS_INVALID."""
        q = _make_quote(QuoteStatus.STALE, timedelta(minutes=5))
        result = self.policy.check(q, _ITEM_ID, _NOW + timedelta(seconds=30))
        assert result.allowed is False
        assert result.rejection_reason == ReservationRejectionReason.QUOTE_STATUS_INVALID

    def test_denies_halted_with_status_invalid_reason(self):
        q = _make_quote(QuoteStatus.HALTED, timedelta(hours=1))
        result = self.policy.check(q, _ITEM_ID, _NOW)
        assert result.allowed is False
        assert result.rejection_reason == ReservationRejectionReason.QUOTE_STATUS_INVALID

    def test_result_carries_policy_name(self):
        q = _make_quote(QuoteStatus.FRESH, timedelta(seconds=90))
        result = self.policy.check(q, _ITEM_ID, _NOW)
        assert "DefaultQuotePolicy" in result.policy


# ---------------------------------------------------------------------------
# CompositePolicy
# ---------------------------------------------------------------------------

class _AlwaysPermit:
    def check(self, quote: Quote, item_id: int, now: datetime) -> PolicyResult:
        return PolicyResult.permit(policy="AlwaysPermit")


class _AlwaysDeny:
    def __init__(self, reason: ReservationRejectionReason):
        self._reason = reason

    def check(self, quote: Quote, item_id: int, now: datetime) -> PolicyResult:
        return PolicyResult.deny(reason=self._reason, policy="AlwaysDeny")


class TestCompositePolicy:
    def test_all_permit_returns_permit(self):
        policy = CompositePolicy([_AlwaysPermit(), _AlwaysPermit()])
        result = policy.check(_make_quote(), _ITEM_ID, _NOW)
        assert result.allowed is True

    def test_first_denial_short_circuits(self):
        policy = CompositePolicy([
            _AlwaysDeny(ReservationRejectionReason.TRADING_HALTED),
            _AlwaysPermit(),
        ])
        result = policy.check(_make_quote(), _ITEM_ID, _NOW)
        assert result.allowed is False
        assert result.rejection_reason == ReservationRejectionReason.TRADING_HALTED

    def test_second_policy_denial_carries_its_reason(self):
        policy = CompositePolicy([
            _AlwaysPermit(),
            _AlwaysDeny(ReservationRejectionReason.ITEM_ALREADY_RESERVED),
            _AlwaysPermit(),
        ])
        result = policy.check(_make_quote(), _ITEM_ID, _NOW)
        assert result.rejection_reason == ReservationRejectionReason.ITEM_ALREADY_RESERVED

    def test_ordering_quote_then_trading_halt(self):
        """Expired quote is caught by DefaultQuotePolicy before TradingHalt I/O."""
        stale = _make_quote(QuoteStatus.FRESH, timedelta(seconds=90))
        policy = CompositePolicy([
            DefaultQuotePolicy(),
            _AlwaysDeny(ReservationRejectionReason.TRADING_HALTED),
        ])
        expired_time = _NOW + timedelta(seconds=91)
        result = policy.check(stale, _ITEM_ID, expired_time)
        assert result.rejection_reason == ReservationRejectionReason.QUOTE_EXPIRED

    def test_empty_composite_permits(self):
        policy = CompositePolicy([])
        result = policy.check(_make_quote(), _ITEM_ID, _NOW)
        assert result.allowed is True
