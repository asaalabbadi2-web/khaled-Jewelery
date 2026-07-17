"""CheckoutService — confirms payment, creates Order, and completes Reservation.

This is the critical coordination point between the Payment, Order, and
Reservation domains. It runs entirely within one atomic transaction
(CheckoutUnitOfWork), so all three writes commit or roll back together:

    1. Create Order (CONFIRMED)          — OrderService.create_from_reservation()
    2. Update Reservation → COMPLETED    — reservation_repository.update_status()
    3. Enqueue OrderCreated              — outbox.enqueue()  [done by OrderService]
    4. Enqueue ReservationConfirmed      — outbox.enqueue()  [done here]

Flow:
    PaymentService.confirm() [PAID]
        ↓
    CheckoutService.confirm()
        ↓ OrderService.create_from_reservation()
        ↓ reservation_repository.update_status(COMPLETED)
        ↓ outbox.enqueue(ReservationConfirmed)
        ↓ return (reservation, order)

The caller (HTTP webhook handler) commits after this returns.

Exceptions:
    ReservationNotFoundException → 404
    ReservationStatusError       → 409
    ReservationExpiredError      → 410 (webhook arrived after valid_until)

Each non-happy-path exception leaves the UoW uncommitted — the caller
maps them to idempotent 204s (already confirmed or already expired).
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from yasargold_domain.orders.order import Order
from yasargold_domain.orders.service import OrderService
from yasargold_domain.orders.unit_of_work import CheckoutUnitOfWork
from yasargold_domain.reservation.events import ReservationConfirmed
from yasargold_domain.reservation.exceptions import (
    ReservationExpiredError,
    ReservationNotFoundException,
    ReservationStatusError,
)
from yasargold_domain.reservation.repository import ReservationRecord
from yasargold_domain.shared.identifiers import PaymentIntentId, ReservationId


class CheckoutService:
    """Coordinates Order creation and Reservation completion atomically.

    Stateless — safe to instantiate once and share across requests.
    """

    def __init__(self, order_service: OrderService | None = None) -> None:
        self._order_service = order_service or OrderService()

    def confirm(
        self,
        reservation_id: ReservationId,
        payment_intent_id: PaymentIntentId,
        amount: Decimal,
        currency: str,
        uow: CheckoutUnitOfWork,
        now: datetime | None = None,
    ) -> tuple[ReservationRecord, Order]:
        """Confirm checkout: create Order + complete Reservation atomically.

        Returns (completed_reservation, created_order).
        Caller is responsible for uow.commit().

        Raises:
            ReservationNotFoundException: reservation_id does not exist.
            ReservationStatusError:       reservation is not ACTIVE.
            ReservationExpiredError:      valid_until has elapsed.
        """
        t = now or datetime.now(timezone.utc)

        record = uow.reservation_repository.find_by_id(reservation_id)
        if record is None:
            raise ReservationNotFoundException(str(reservation_id))

        if record.status != "ACTIVE":
            raise ReservationStatusError(
                str(reservation_id),
                current_status=record.status,
                expected="ACTIVE",
            )

        valid_until = record.valid_until
        if valid_until.tzinfo is None:
            valid_until = valid_until.replace(tzinfo=timezone.utc)
        if t >= valid_until:
            raise ReservationExpiredError(str(reservation_id), expired_at=valid_until)

        # Create Order first — if this fails, nothing is committed.
        # uow satisfies OrderUnitOfWork structurally (has .repository and .outbox).
        order = self._order_service.create_from_reservation(
            reservation_id=reservation_id,
            item_id=record.item_id,
            payment_intent_id=payment_intent_id,
            amount=amount,
            currency=currency,
            uow=uow,  # type: ignore[arg-type]  # structural subtype
            now=t,
            customer_ref=record.customer_phone,
        )

        # Complete the Reservation.
        uow.reservation_repository.update_status(reservation_id, "COMPLETED")

        uow.outbox.enqueue(
            ReservationConfirmed(
                reservation_id=reservation_id,
                quote_id=record.quote_id,
                item_id=record.item_id,
                payment_intent_id=payment_intent_id,
            )
        )

        from dataclasses import replace
        return replace(record, status="COMPLETED"), order
