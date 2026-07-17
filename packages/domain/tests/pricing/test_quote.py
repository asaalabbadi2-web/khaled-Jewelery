"""Unit tests for Quote domain behaviour.

These tests have zero infrastructure dependencies — no DB, no HTTP, no FastAPI.
They verify the business rules of the Quote Aggregate directly.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from yasargold_domain.pricing.quotes import Quote, QuoteId, QuoteStatus

_NOW = datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc)
_RATE = Decimal("230.00")
_KARAT_RATE = Decimal("201.25")


def _make_quote(
    status: QuoteStatus = QuoteStatus.FRESH,
    valid_until_offset: timedelta = timedelta(seconds=90),
    id: QuoteId | None = None,
    item_id: int | None = None,
) -> Quote:
    issued = _NOW
    return Quote(
        status=status,
        gold_price_id=1,
        gold_rate_per_gram_24k=_RATE,
        karat_rate_per_gram=_KARAT_RATE,
        issued_at=issued,
        valid_from=issued,
        valid_until=issued + valid_until_offset,
        pricing_engine_version="v1",
        id=id,
        item_id=item_id,
    )


# ---------------------------------------------------------------------------
# QuoteStatus properties
# ---------------------------------------------------------------------------

class TestQuoteStatusProperties:
    def test_fresh_allows_reservation(self):
        assert QuoteStatus.FRESH.allows_reservation is True

    def test_locked_allows_reservation(self):
        assert QuoteStatus.LOCKED.allows_reservation is True

    def test_stale_does_not_allow_reservation(self):
        assert QuoteStatus.STALE.allows_reservation is False

    def test_halted_does_not_allow_reservation(self):
        assert QuoteStatus.HALTED.allows_reservation is False

    def test_expired_does_not_allow_reservation(self):
        assert QuoteStatus.EXPIRED.allows_reservation is False

    def test_invalid_does_not_allow_reservation(self):
        assert QuoteStatus.INVALID.allows_reservation is False

    def test_terminal_states(self):
        assert QuoteStatus.HALTED.is_terminal is True
        assert QuoteStatus.EXPIRED.is_terminal is True
        assert QuoteStatus.INVALID.is_terminal is True
        assert QuoteStatus.FRESH.is_terminal is False
        assert QuoteStatus.STALE.is_terminal is False
        assert QuoteStatus.LOCKED.is_terminal is False

    def test_requires_quote_id(self):
        assert QuoteStatus.LOCKED.requires_quote_id is True
        assert QuoteStatus.EXPIRED.requires_quote_id is True
        assert QuoteStatus.INVALID.requires_quote_id is True
        assert QuoteStatus.FRESH.requires_quote_id is False


# ---------------------------------------------------------------------------
# Quote.is_expired
# ---------------------------------------------------------------------------

class TestQuoteIsExpired:
    def test_not_expired_before_valid_until(self):
        q = _make_quote(valid_until_offset=timedelta(seconds=60))
        now = _NOW + timedelta(seconds=30)
        assert q.is_expired(now) is False

    def test_expired_after_valid_until(self):
        q = _make_quote(valid_until_offset=timedelta(seconds=60))
        now = _NOW + timedelta(seconds=61)
        assert q.is_expired(now) is True

    def test_expired_exactly_at_valid_until(self):
        q = _make_quote(valid_until_offset=timedelta(seconds=60))
        now = _NOW + timedelta(seconds=60)
        assert q.is_expired(now) is True


# ---------------------------------------------------------------------------
# Quote.is_valid
# ---------------------------------------------------------------------------

class TestQuoteIsValid:
    def test_fresh_within_window_is_valid(self):
        q = _make_quote(QuoteStatus.FRESH, timedelta(seconds=90))
        assert q.is_valid(_NOW + timedelta(seconds=45)) is True

    def test_fresh_after_window_is_invalid(self):
        q = _make_quote(QuoteStatus.FRESH, timedelta(seconds=90))
        assert q.is_valid(_NOW + timedelta(seconds=91)) is False

    def test_terminal_status_is_invalid_even_if_not_expired(self):
        q = _make_quote(QuoteStatus.HALTED, timedelta(hours=1))
        assert q.is_valid(_NOW) is False


# ---------------------------------------------------------------------------
# Quote.can_reserve — combines status AND time
# ---------------------------------------------------------------------------

class TestQuoteCanReserve:
    def test_fresh_within_window_can_reserve(self):
        q = _make_quote(QuoteStatus.FRESH, timedelta(seconds=90))
        assert q.can_reserve(_NOW + timedelta(seconds=30)) is True

    def test_fresh_after_window_cannot_reserve(self):
        """Status is FRESH but valid_until has elapsed — must be rejected."""
        q = _make_quote(QuoteStatus.FRESH, timedelta(seconds=90))
        assert q.can_reserve(_NOW + timedelta(seconds=91)) is False

    def test_stale_within_window_cannot_reserve(self):
        q = _make_quote(QuoteStatus.STALE, timedelta(minutes=5))
        assert q.can_reserve(_NOW + timedelta(seconds=30)) is False

    def test_locked_within_window_can_reserve(self):
        q = _make_quote(QuoteStatus.LOCKED, timedelta(minutes=10),
                        id=QuoteId("qt_abc"))
        assert q.can_reserve(_NOW + timedelta(minutes=5)) is True

    def test_locked_after_window_cannot_reserve(self):
        q = _make_quote(QuoteStatus.LOCKED, timedelta(minutes=10),
                        id=QuoteId("qt_abc"))
        assert q.can_reserve(_NOW + timedelta(minutes=11)) is False


# ---------------------------------------------------------------------------
# Quote.can_checkout
# ---------------------------------------------------------------------------

class TestQuoteCanCheckout:
    def test_locked_within_window_can_checkout(self):
        q = _make_quote(QuoteStatus.LOCKED, timedelta(minutes=10),
                        id=QuoteId("qt_abc"))
        assert q.can_checkout(_NOW + timedelta(minutes=5)) is True

    def test_fresh_cannot_checkout(self):
        """FRESH quotes cannot go directly to checkout — must be LOCKED first."""
        q = _make_quote(QuoteStatus.FRESH, timedelta(seconds=90))
        assert q.can_checkout(_NOW) is False

    def test_locked_expired_cannot_checkout(self):
        q = _make_quote(QuoteStatus.LOCKED, timedelta(minutes=10),
                        id=QuoteId("qt_abc"))
        assert q.can_checkout(_NOW + timedelta(minutes=11)) is False


# ---------------------------------------------------------------------------
# Quote immutability
# ---------------------------------------------------------------------------

class TestQuoteImmutability:
    def test_quote_is_frozen(self):
        q = _make_quote()
        with pytest.raises((AttributeError, TypeError)):
            q.status = QuoteStatus.LOCKED  # type: ignore[misc]
