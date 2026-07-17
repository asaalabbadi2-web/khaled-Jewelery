"""Unit tests for PaymentIntent state machine.

Covers every guard method (can_pay, can_expire, can_confirm, is_terminal)
across all status transitions. No I/O — pure domain logic only.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from yasargold_domain.payment.intent import PaymentIntent, PaymentStatus
from yasargold_domain.shared.identifiers import PaymentIntentId, ReservationId

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 7, 13, 12, 0, 0, tzinfo=timezone.utc)
_RES_ID = ReservationId("res_abc123")
_PI_ID = PaymentIntentId("pi_test0001")


def _make_intent(
    status: PaymentStatus = PaymentStatus.PENDING,
    minutes_until_expiry: int = 15,
) -> PaymentIntent:
    return PaymentIntent(
        id=_PI_ID,
        reservation_id=_RES_ID,
        amount=Decimal("5500.00"),
        currency="SAR",
        status=status,
        created_at=_NOW - timedelta(minutes=1),
        expires_at=_NOW + timedelta(minutes=minutes_until_expiry),
    )


# ---------------------------------------------------------------------------
# PaymentStatus.is_terminal
# ---------------------------------------------------------------------------

class TestPaymentStatusTerminal:
    def test_pending_is_not_terminal(self) -> None:
        assert not PaymentStatus.PENDING.is_terminal

    def test_paid_is_not_terminal(self) -> None:
        # PAID can still transition to REFUND_PENDING (see ADR-013 compensation path)
        assert not PaymentStatus.PAID.is_terminal

    def test_failed_is_terminal(self) -> None:
        assert PaymentStatus.FAILED.is_terminal

    def test_expired_is_terminal(self) -> None:
        assert PaymentStatus.EXPIRED.is_terminal

    def test_refund_pending_is_not_terminal(self) -> None:
        assert not PaymentStatus.REFUND_PENDING.is_terminal

    def test_refunded_is_terminal(self) -> None:
        assert PaymentStatus.REFUNDED.is_terminal


# ---------------------------------------------------------------------------
# can_pay
# ---------------------------------------------------------------------------

class TestCanPay:
    def test_pending_within_window_can_pay(self) -> None:
        assert _make_intent().can_pay(_NOW)

    def test_pending_past_expiry_cannot_pay(self) -> None:
        assert not _make_intent(minutes_until_expiry=-1).can_pay(_NOW)

    def test_exactly_at_expiry_cannot_pay(self) -> None:
        """Boundary: expires_at == now is treated as expired (strict <)."""
        intent = _make_intent(minutes_until_expiry=0)
        assert not intent.can_pay(_NOW)

    def test_one_second_before_expiry_can_pay(self) -> None:
        from dataclasses import replace
        intent = replace(_make_intent(), expires_at=_NOW + timedelta(seconds=1))
        assert intent.can_pay(_NOW)

    def test_paid_status_cannot_pay(self) -> None:
        assert not _make_intent(status=PaymentStatus.PAID).can_pay(_NOW)

    def test_failed_status_cannot_pay(self) -> None:
        assert not _make_intent(status=PaymentStatus.FAILED).can_pay(_NOW)

    def test_expired_status_cannot_pay(self) -> None:
        assert not _make_intent(status=PaymentStatus.EXPIRED).can_pay(_NOW)


# ---------------------------------------------------------------------------
# can_expire
# ---------------------------------------------------------------------------

class TestCanExpire:
    def test_pending_past_expiry_can_expire(self) -> None:
        assert _make_intent(minutes_until_expiry=-1).can_expire(_NOW)

    def test_exactly_at_expiry_can_expire(self) -> None:
        assert _make_intent(minutes_until_expiry=0).can_expire(_NOW)

    def test_pending_within_window_cannot_expire(self) -> None:
        assert not _make_intent().can_expire(_NOW)

    def test_paid_cannot_expire(self) -> None:
        assert not _make_intent(status=PaymentStatus.PAID).can_expire(_NOW)

    def test_failed_cannot_expire(self) -> None:
        assert not _make_intent(status=PaymentStatus.FAILED).can_expire(_NOW)

    def test_already_expired_cannot_expire_again(self) -> None:
        assert not _make_intent(status=PaymentStatus.EXPIRED, minutes_until_expiry=-1).can_expire(_NOW)


# ---------------------------------------------------------------------------
# can_confirm (drives CheckoutService)
# ---------------------------------------------------------------------------

class TestCanConfirm:
    def test_paid_can_confirm(self) -> None:
        assert _make_intent(status=PaymentStatus.PAID).can_confirm()

    def test_pending_cannot_confirm(self) -> None:
        assert not _make_intent(status=PaymentStatus.PENDING).can_confirm()

    def test_failed_cannot_confirm(self) -> None:
        assert not _make_intent(status=PaymentStatus.FAILED).can_confirm()

    def test_expired_cannot_confirm(self) -> None:
        assert not _make_intent(status=PaymentStatus.EXPIRED).can_confirm()


# ---------------------------------------------------------------------------
# is_terminal (aggregate property)
# ---------------------------------------------------------------------------

class TestIsTerminal:
    def test_pending_is_not_terminal(self) -> None:
        assert not _make_intent(status=PaymentStatus.PENDING).is_terminal

    def test_paid_is_not_terminal(self) -> None:
        # PAID → REFUND_PENDING is valid, so PAID is not terminal
        assert not _make_intent(status=PaymentStatus.PAID).is_terminal

    def test_failed_is_terminal(self) -> None:
        assert _make_intent(status=PaymentStatus.FAILED).is_terminal

    def test_expired_is_terminal(self) -> None:
        assert _make_intent(status=PaymentStatus.EXPIRED).is_terminal

    def test_refund_pending_is_not_terminal(self) -> None:
        assert not _make_intent(status=PaymentStatus.REFUND_PENDING).is_terminal

    def test_refunded_is_terminal(self) -> None:
        assert _make_intent(status=PaymentStatus.REFUNDED).is_terminal
