"""Typed domain exceptions for the Reservation bounded context.

Raised by ReservationService; caught by the application layer (HTTP handler,
CLI command, etc.) and translated into user-facing error responses.

These exceptions carry typed, structured data — not raw strings — so that
HTTP handlers can produce correct status codes and error codes without
parsing exception messages.
"""
from __future__ import annotations

from yasargold_domain.pricing.reservation_policy import ReservationRejectionReason


class ReservationDomainError(Exception):
    """Base class for all reservation domain errors."""


class ReservationDenied(ReservationDomainError):
    """A policy check rejected the reservation request.

    reason: typed enum — maps 1:1 to API error codes.
    policy: name of the policy that raised the denial (for audit logs).
    """

    def __init__(self, reason: ReservationRejectionReason, policy: str = "unknown") -> None:
        self.reason = reason
        self.policy = policy
        super().__init__(f"Reservation denied by {policy}: {reason.value}")


class ItemAlreadyReservedException(ReservationDomainError):
    """The inventory store holds an active lock on this item.

    Raised by InventoryReservationRepository.lock_item() when
    SELECT FOR UPDATE NOWAIT finds a conflicting row.

    Application layer translates this to HTTP 409 Conflict.
    """

    def __init__(self, item_id: int) -> None:
        self.item_id = item_id
        super().__init__(f"Item {item_id} is already reserved")


class ReservationNotFoundException(ReservationDomainError):
    """No reservation exists for the given identifier."""

    def __init__(self, reservation_id: str) -> None:
        self.reservation_id = reservation_id
        super().__init__(f"Reservation '{reservation_id}' not found")


class ReservationExpiredError(ReservationDomainError):
    """The reservation's valid_until has elapsed.

    Raised by CheckoutService when a payment webhook arrives after expiry.
    Application layer translates this to HTTP 410 Gone (not 422 — the resource
    existed but is permanently gone; retrying with the same reservation_id
    will never succeed).
    """

    def __init__(self, reservation_id: str, expired_at: object) -> None:
        self.reservation_id = reservation_id
        self.expired_at = expired_at
        super().__init__(f"Reservation '{reservation_id}' expired at {expired_at}")


class ReservationStatusError(ReservationDomainError):
    """The reservation is not in a state that permits the requested transition.

    Example: confirming a CANCELLED reservation.
    """

    def __init__(self, reservation_id: str, current_status: str, expected: str) -> None:
        self.reservation_id = reservation_id
        self.current_status = current_status
        self.expected = expected
        super().__init__(
            f"Reservation '{reservation_id}' is {current_status}, expected {expected}"
        )
