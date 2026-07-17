"""Unit tests for Domain Events and Value Object identifiers."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from yasargold_domain.reservation.events import (
    DomainEvent,
    ReservationCancelled,
    ReservationConfirmed,
    ReservationCreated,
    ReservationExpired,
)
from yasargold_domain.shared.identifiers import (
    GoldPriceId,
    ItemId,
    QuoteId,
    ReservationId,
)

_NOW = datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Value Object identifiers — type safety at the boundary
# ---------------------------------------------------------------------------

class TestIdentifiers:
    def test_item_id_is_int(self):
        assert isinstance(ItemId(42), int)

    def test_gold_price_id_is_int(self):
        assert isinstance(GoldPriceId(18452), int)

    def test_quote_id_is_str(self):
        assert isinstance(QuoteId("qt_abc"), str)

    def test_reservation_id_is_str(self):
        assert isinstance(ReservationId("res_xyz"), str)

    def test_distinct_int_ids_are_not_interchangeable_at_runtime(self):
        """NewType is erased at runtime — this documents the design intent."""
        item = ItemId(1)
        price = GoldPriceId(1)
        # Both are int(1) at runtime — the type checker catches the swap
        assert item == price  # expected: same runtime value

    def test_distinct_str_ids_are_not_interchangeable_at_runtime(self):
        q = QuoteId("abc")
        r = ReservationId("abc")
        assert q == r  # same reasoning — type checker enforces distinction


# ---------------------------------------------------------------------------
# Domain Events — structure and invariants
# ---------------------------------------------------------------------------

class TestDomainEventBase:
    def test_event_has_unique_id(self):
        e1 = ReservationCreated(
            reservation_id=ReservationId("res_1"),
            quote_id=QuoteId("qt_1"),
            item_id=ItemId(1),
            gold_price_id=GoldPriceId(100),
            locked_rate_per_gram_24k=Decimal("230.00"),
            pricing_engine_version="v1",
            valid_until=_NOW,
        )
        e2 = ReservationCreated(
            reservation_id=ReservationId("res_2"),
            quote_id=QuoteId("qt_2"),
            item_id=ItemId(2),
            gold_price_id=GoldPriceId(100),
            locked_rate_per_gram_24k=Decimal("230.00"),
            pricing_engine_version="v1",
            valid_until=_NOW,
        )
        assert e1.event_id != e2.event_id

    def test_event_type_is_fully_qualified(self):
        e = ReservationCreated(
            reservation_id=ReservationId("res_1"),
            quote_id=QuoteId("qt_1"),
            item_id=ItemId(1),
            gold_price_id=GoldPriceId(100),
            locked_rate_per_gram_24k=Decimal("230.00"),
            pricing_engine_version="v1",
            valid_until=_NOW,
        )
        assert "ReservationCreated" in e.event_type
        assert "yasargold_domain" in e.event_type

    def test_event_is_immutable(self):
        e = ReservationExpired(
            reservation_id=ReservationId("res_1"),
            quote_id=QuoteId("qt_1"),
            item_id=ItemId(1),
        )
        with pytest.raises((AttributeError, TypeError)):
            e.reservation_id = ReservationId("res_2")  # type: ignore[misc]

    def test_occurred_at_is_set_automatically(self):
        e = ReservationCancelled(
            reservation_id=ReservationId("res_1"),
            quote_id=QuoteId("qt_1"),
            item_id=ItemId(1),
            cancelled_by="customer",
        )
        assert isinstance(e.occurred_at, datetime)


class TestReservationCreated:
    def _make(self) -> ReservationCreated:
        return ReservationCreated(
            reservation_id=ReservationId("res_abc"),
            quote_id=QuoteId("qt_xyz"),
            item_id=ItemId(42),
            gold_price_id=GoldPriceId(18452),
            locked_rate_per_gram_24k=Decimal("230.00"),
            pricing_engine_version="v1",
            valid_until=_NOW,
        )

    def test_carries_all_audit_fields(self):
        e = self._make()
        assert e.gold_price_id == GoldPriceId(18452)
        assert e.locked_rate_per_gram_24k == Decimal("230.00")
        assert e.pricing_engine_version == "v1"

    def test_rate_is_decimal_not_float(self):
        e = self._make()
        assert isinstance(e.locked_rate_per_gram_24k, Decimal)


class TestReservationConfirmed:
    def test_carries_payment_intent_id(self):
        from yasargold_domain.shared.identifiers import PaymentIntentId
        e = ReservationConfirmed(
            reservation_id=ReservationId("res_1"),
            quote_id=QuoteId("qt_1"),
            item_id=ItemId(1),
            payment_intent_id=PaymentIntentId("pi_test_abc123"),
        )
        assert e.payment_intent_id == PaymentIntentId("pi_test_abc123")


class TestEventIdempotency:
    def test_two_events_with_same_data_have_different_ids(self):
        """Each event is a unique fact — even with identical payload."""
        kwargs = dict(
            reservation_id=ReservationId("res_1"),
            quote_id=QuoteId("qt_1"),
            item_id=ItemId(1),
            cancelled_by="customer",
        )
        e1 = ReservationCancelled(**kwargs)
        e2 = ReservationCancelled(**kwargs)
        assert e1.event_id != e2.event_id
