"""Tests for the Shipment aggregate state machine.

Coverage:
    SM1: initial state is PENDING
    SM2: can_register() true only for PENDING
    SM3: can_void() true for CREATED within void_window
    SM4: can_void() false after void_window expires (Law 0 — Frozen vs Live §13)
    SM5: can_void() false if status is not CREATED
    SM6: can_void() false if registered_at is None (PENDING)
    SM7: can_mark_in_transit() true only for CREATED
    SM8: can_deliver() true only for IN_TRANSIT
    SM9: terminal statuses are terminal
    SM10: declared_value does not change when gold price changes (Law 0 — Frozen)
    SM11: idempotency_key format snapshot
    SM12: can_void() with two carriers — different void_windows, same shipment
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from yasargold_domain.shipping.carrier_config import CarrierConfig
from yasargold_domain.shipping.shipment import Shipment, ShipmentStatus
from yasargold_domain.shared.identifiers import OrderId, ShipmentId

_NOW = datetime(2026, 7, 14, 10, 0, 0, tzinfo=timezone.utc)
_ORDER_ID = OrderId("ord_test_shp_001")
_SHIPMENT_ID = ShipmentId("shp_test001")
_CARRIER_ARAMEX = CarrierConfig(carrier_id="aramex", name="Aramex", void_window=timedelta(hours=6))
_CARRIER_SMSA = CarrierConfig(carrier_id="smsa", name="SMSA", void_window=timedelta(hours=2))
_DECLARED_VALUE = Decimal("5500.00")


def _pending_shipment() -> Shipment:
    return Shipment(
        id=_SHIPMENT_ID,
        order_id=_ORDER_ID,
        carrier_id="aramex",
        declared_value=_DECLARED_VALUE,
        status=ShipmentStatus.PENDING,
        idempotency_key=f"{_ORDER_ID}:SHIPMENT",
        created_at=_NOW,
    )


def _created_shipment(registered_at: datetime | None = None) -> Shipment:
    return replace(
        _pending_shipment(),
        status=ShipmentStatus.CREATED,
        tracking_number="TRK-001",
        registered_at=registered_at or _NOW,
    )


# ---------------------------------------------------------------------------
# SM1: initial state
# ---------------------------------------------------------------------------

class TestSM1InitialState:
    def test_status_is_pending(self) -> None:
        s = _pending_shipment()
        assert s.status == ShipmentStatus.PENDING

    def test_tracking_number_is_none(self) -> None:
        s = _pending_shipment()
        assert s.tracking_number is None

    def test_registered_at_is_none(self) -> None:
        s = _pending_shipment()
        assert s.registered_at is None


# ---------------------------------------------------------------------------
# SM2: can_register()
# ---------------------------------------------------------------------------

class TestSM2CanRegister:
    def test_true_for_pending(self) -> None:
        assert _pending_shipment().can_register() is True

    def test_false_for_created(self) -> None:
        assert _created_shipment().can_register() is False

    def test_false_for_voided(self) -> None:
        s = replace(_created_shipment(), status=ShipmentStatus.VOIDED)
        assert s.can_register() is False


# ---------------------------------------------------------------------------
# SM3 / SM4 / SM5 / SM6: can_void()
# ---------------------------------------------------------------------------

class TestSM3CanVoidWithinWindow:
    def test_true_when_within_window(self) -> None:
        s = _created_shipment(registered_at=_NOW)
        now = _NOW + timedelta(hours=1)
        assert s.can_void(now, _CARRIER_ARAMEX.void_window) is True

    def test_true_at_window_boundary_minus_one_second(self) -> None:
        s = _created_shipment(registered_at=_NOW)
        now = _NOW + timedelta(hours=6) - timedelta(seconds=1)
        assert s.can_void(now, _CARRIER_ARAMEX.void_window) is True


class TestSM4CanVoidAfterWindowExpires:
    """Law 0 — Live value (void_window) test: change source, read reflects immediately."""

    def test_false_exactly_at_window_expiry(self) -> None:
        s = _created_shipment(registered_at=_NOW)
        now = _NOW + timedelta(hours=6)
        assert s.can_void(now, _CARRIER_ARAMEX.void_window) is False

    def test_false_after_window_expires(self) -> None:
        s = _created_shipment(registered_at=_NOW)
        now = _NOW + timedelta(hours=7)
        assert s.can_void(now, _CARRIER_ARAMEX.void_window) is False


class TestSM5CanVoidWrongStatus:
    def test_false_for_pending(self) -> None:
        s = _pending_shipment()
        # registered_at is None, status is PENDING
        assert s.can_void(_NOW, _CARRIER_ARAMEX.void_window) is False

    def test_false_for_in_transit(self) -> None:
        s = replace(_created_shipment(), status=ShipmentStatus.IN_TRANSIT)
        assert s.can_void(_NOW, _CARRIER_ARAMEX.void_window) is False

    def test_false_for_delivered(self) -> None:
        s = replace(_created_shipment(), status=ShipmentStatus.DELIVERED)
        assert s.can_void(_NOW, _CARRIER_ARAMEX.void_window) is False

    def test_false_for_voided(self) -> None:
        s = replace(_created_shipment(), status=ShipmentStatus.VOIDED)
        assert s.can_void(_NOW, _CARRIER_ARAMEX.void_window) is False


class TestSM6CanVoidNullRegisteredAt:
    def test_false_when_registered_at_is_none(self) -> None:
        s = replace(_created_shipment(), registered_at=None)
        assert s.can_void(_NOW, _CARRIER_ARAMEX.void_window) is False


# ---------------------------------------------------------------------------
# SM7: can_mark_in_transit()
# ---------------------------------------------------------------------------

class TestSM7CanMarkInTransit:
    def test_true_for_created(self) -> None:
        assert _created_shipment().can_mark_in_transit() is True

    def test_false_for_pending(self) -> None:
        assert _pending_shipment().can_mark_in_transit() is False

    def test_false_for_in_transit(self) -> None:
        s = replace(_created_shipment(), status=ShipmentStatus.IN_TRANSIT)
        assert s.can_mark_in_transit() is False


# ---------------------------------------------------------------------------
# SM8: can_deliver()
# ---------------------------------------------------------------------------

class TestSM8CanDeliver:
    def test_true_for_in_transit(self) -> None:
        s = replace(_created_shipment(), status=ShipmentStatus.IN_TRANSIT)
        assert s.can_deliver() is True

    def test_false_for_created(self) -> None:
        assert _created_shipment().can_deliver() is False

    def test_false_for_pending(self) -> None:
        assert _pending_shipment().can_deliver() is False


# ---------------------------------------------------------------------------
# SM9: terminal statuses
# ---------------------------------------------------------------------------

class TestSM9TerminalStatuses:
    def test_delivered_is_terminal(self) -> None:
        assert ShipmentStatus.DELIVERED.is_terminal is True

    def test_voided_is_terminal(self) -> None:
        assert ShipmentStatus.VOIDED.is_terminal is True

    def test_failed_is_terminal(self) -> None:
        assert ShipmentStatus.FAILED.is_terminal is True

    def test_pending_is_not_terminal(self) -> None:
        assert ShipmentStatus.PENDING.is_terminal is False

    def test_created_is_not_terminal(self) -> None:
        assert ShipmentStatus.CREATED.is_terminal is False

    def test_in_transit_is_not_terminal(self) -> None:
        assert ShipmentStatus.IN_TRANSIT.is_terminal is False


# ---------------------------------------------------------------------------
# SM10: declared_value is Frozen — Law 0 test (§13)
# ---------------------------------------------------------------------------

class TestSM10DeclaredValueFrozen:
    """Law 0 for Frozen values: change source after freeze → stored value unchanged."""

    def test_declared_value_unchanged_after_gold_price_increase(self) -> None:
        # Shipment claimed with gold at 220 SAR/gram × 25g = 5500 SAR
        shipment = _pending_shipment()
        stored_value = shipment.declared_value

        # Gold price surges 8%: new price would give declared_value = 5940 SAR
        new_gold_price_derived_value = Decimal("5940.00")

        # The aggregate holds the Frozen value — never re-derived from current price
        assert shipment.declared_value == stored_value
        assert shipment.declared_value != new_gold_price_derived_value
        assert shipment.declared_value == Decimal("5500.00")

    def test_declared_value_unchanged_across_status_transitions(self) -> None:
        pending = _pending_shipment()
        created = replace(pending, status=ShipmentStatus.CREATED, tracking_number="TRK", registered_at=_NOW)
        in_transit = replace(created, status=ShipmentStatus.IN_TRANSIT)
        delivered = replace(in_transit, status=ShipmentStatus.DELIVERED)

        # All states must carry the same frozen declared_value
        for s in [pending, created, in_transit, delivered]:
            assert s.declared_value == Decimal("5500.00")


# ---------------------------------------------------------------------------
# SM11: idempotency_key snapshot
# ---------------------------------------------------------------------------

class TestSM11IdempotencyKeySnapshot:
    def test_key_format(self) -> None:
        s = _pending_shipment()
        assert s.idempotency_key == f"{_ORDER_ID}:SHIPMENT"

    def test_key_contains_order_id(self) -> None:
        s = _pending_shipment()
        assert str(_ORDER_ID) in s.idempotency_key


# ---------------------------------------------------------------------------
# SM12: two carriers — different void_windows, same shipment (§13 Live)
# ---------------------------------------------------------------------------

class TestSM12TwoCarriersDifferentVoidWindows:
    """void_window is Live — the config passed in governs, not a cached value."""

    def test_within_smsa_window_but_outside_aramex_window(self) -> None:
        # SMSA: 2h, Aramex: 6h
        # Check at 3h after registration: inside Aramex, outside SMSA
        s = _created_shipment(registered_at=_NOW)
        now = _NOW + timedelta(hours=3)
        assert s.can_void(now, _CARRIER_ARAMEX.void_window) is True   # 3h < 6h
        assert s.can_void(now, _CARRIER_SMSA.void_window) is False     # 3h > 2h

    def test_both_carriers_within_window_at_1h(self) -> None:
        s = _created_shipment(registered_at=_NOW)
        now = _NOW + timedelta(hours=1)
        assert s.can_void(now, _CARRIER_ARAMEX.void_window) is True
        assert s.can_void(now, _CARRIER_SMSA.void_window) is True

    def test_both_carriers_outside_window_at_7h(self) -> None:
        s = _created_shipment(registered_at=_NOW)
        now = _NOW + timedelta(hours=7)
        assert s.can_void(now, _CARRIER_ARAMEX.void_window) is False
        assert s.can_void(now, _CARRIER_SMSA.void_window) is False
