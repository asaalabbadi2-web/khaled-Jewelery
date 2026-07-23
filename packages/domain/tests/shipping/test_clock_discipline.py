"""Clock Discipline proof — host drift must not affect domain decisions.

ADR-015 §Clock Discipline (Presentation vs Decision time):
  DECISION TIME obtains `now` via the injected Clock Provider.
  Container NTP is for logs/metrics only — not for business decisions.

This module provides two proof classes:

  TestClockDisciplineBaseline
      Sanity checks: injecting the correct `now` gives the expected
      decision, in both the "within window" and "past window" cases.

  TestClockDisciplineHostDrift
      The real proof: `datetime.now` in the module is patched to simulate
      container-clock drift in both directions. The domain decision must
      follow the INJECTED `now`, not the (wrong) host clock.

      Host +3 h drift:
        `expires_at` is 2 h away. Injected now says NOT expired.
        Host says 1 h past expires_at → would say expired (WRONG).
        Proof: with injected now, can_expire() is False.

      Host −2 h drift:
        `expires_at` is 1 h in the past. Injected now says expired.
        Host is 2 h behind → says 1 h before expires_at → NOT expired (WRONG).
        Proof: with injected now, can_expire() is True.

      Decisive third case:
        Same intent, same real moment. Host says "early"; injected says "expired".
        Result must follow injected → False (expired).

Subject — primary: PaymentIntent.can_expire(now)
    Has the `now or datetime.now()` fallback, so patching datetime.now
    in the module DOES affect the `now=None` path — making the contrast
    between injected vs host-clock visible in a single test.

Subject — secondary: Shipment.can_void(now, void_window)
    Pure injection; no fallback. Used in the baseline tests to demonstrate
    the reference model that every new domain decision should follow.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest

from yasargold_domain.payment.intent import PaymentIntent, PaymentStatus
from yasargold_domain.shared.identifiers import (
    OrderId,
    PaymentIntentId,
    ReservationId,
    ShipmentId,
)
from yasargold_domain.shipping.shipment import Shipment, ShipmentStatus

# ──────────────────────────────────────────────────────────────────────────────
# Shared constants
# ──────────────────────────────────────────────────────────────────────────────

# A fixed "true" now — what the DB clock / injected provider returns.
_TRUE_NOW = datetime(2026, 7, 14, 10, 0, 0, tzinfo=timezone.utc)
_VOID_WINDOW = timedelta(hours=2)
_REGISTERED_AT = _TRUE_NOW - timedelta(hours=1)  # registered 1 h ago → 1 h of 2-h window elapsed


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_shipment() -> Shipment:
    return Shipment(
        id=ShipmentId("shp_clockdiscipline_001"),
        order_id=OrderId("ord_clockdiscipline_001"),
        carrier_id="aramex",
        declared_value=Decimal("1500.00"),
        status=ShipmentStatus.CREATED,
        idempotency_key="idem_clockdiscipline_001",
        registered_at=_REGISTERED_AT,
    )


def _make_intent(expires_at: datetime) -> PaymentIntent:
    return PaymentIntent(
        id=PaymentIntentId("pi_clockdiscipline_001"),
        reservation_id=ReservationId("res_clockdiscipline_001"),
        amount=Decimal("1500.00"),
        currency="SAR",
        status=PaymentStatus.PENDING,
        created_at=_TRUE_NOW - timedelta(hours=1),
        expires_at=expires_at,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Baseline — pure injection model (Shipment.can_void)
# ──────────────────────────────────────────────────────────────────────────────

class TestClockDisciplineBaseline:
    """Sanity: Shipment.can_void is a pure function — only injected `now` matters."""

    def test_can_void_true_when_within_window(self):
        # 1 h elapsed of a 2-h window → can still void
        assert _make_shipment().can_void(_TRUE_NOW, _VOID_WINDOW) is True

    def test_can_void_false_when_outside_window(self):
        # 2 h 1 min elapsed → window closed
        assert _make_shipment().can_void(
            _TRUE_NOW + timedelta(hours=1, minutes=1), _VOID_WINDOW
        ) is False


# ──────────────────────────────────────────────────────────────────────────────
# Host-drift proofs — PaymentIntent.can_expire(now)
# ──────────────────────────────────────────────────────────────────────────────

class TestClockDisciplineHostDrift:
    """Prove domain decisions are invariant to host-clock drift.

    We patch `datetime.now` inside the payment.intent module to simulate
    container drift. The injected `now=_TRUE_NOW` remains correct.
    The assertion proves the injected value controls the decision — not
    what the host clock would return.
    """

    def test_positive_drift_three_hours_injected_wins(self):
        """Host clock is +3 h ahead; injected now is correct → not expired."""
        # expires 2 h from true now; host thinks it's 3 h from now → past expiry
        intent = _make_intent(expires_at=_TRUE_NOW + timedelta(hours=2))
        drifted = _TRUE_NOW + timedelta(hours=3)  # 1 h past expires_at

        with patch("yasargold_domain.payment.intent.datetime") as mock_dt:
            mock_dt.now.return_value = drifted

            result_injected = intent.can_expire(now=_TRUE_NOW)   # 2 h before expiry
            result_host_only = intent.can_expire(now=None)        # reads patched clock

        assert result_injected is False, (
            "Injected _TRUE_NOW (2 h before expiry) must say not-expired"
        )
        assert result_host_only is True, (
            "Sanity check: host clock (drifted +3 h) would wrongly say expired"
        )

    def test_negative_drift_two_hours_injected_wins(self):
        """Host clock is −2 h behind; injected now is correct → expired."""
        # expired 1 h ago from true now; host thinks it's 1 h before expiry
        intent = _make_intent(expires_at=_TRUE_NOW - timedelta(hours=1))
        drifted = _TRUE_NOW - timedelta(hours=2)  # 1 h before expires_at

        with patch("yasargold_domain.payment.intent.datetime") as mock_dt:
            mock_dt.now.return_value = drifted

            result_injected = intent.can_expire(now=_TRUE_NOW)   # 1 h past expiry
            result_host_only = intent.can_expire(now=None)        # reads patched clock

        assert result_injected is True, (
            "Injected _TRUE_NOW (1 h past expiry) must say expired"
        )
        assert result_host_only is False, (
            "Sanity check: host clock (drifted −2 h) would wrongly say not-expired"
        )

    def test_injected_now_determines_outcome_not_host_clock(self):
        """Decisive: conflicting signals — injected says expired, host says early.

        This is the single clearest proof that the decision follows the
        injected Clock Provider, not the container system clock.
        """
        # expires_at = _TRUE_NOW (exactly at this moment)
        intent = _make_intent(expires_at=_TRUE_NOW)

        host_says_early = _TRUE_NOW - timedelta(hours=2)        # host: 2 h before
        injected_says_expired = _TRUE_NOW + timedelta(seconds=1)  # injected: 1 s past

        with patch("yasargold_domain.payment.intent.datetime") as mock_dt:
            mock_dt.now.return_value = host_says_early

            # Host says early → would return False; injected says expired → True
            result = intent.can_expire(now=injected_says_expired)

        assert result is True, (
            "Decision must follow injected now (expired), not host clock (early)"
        )
