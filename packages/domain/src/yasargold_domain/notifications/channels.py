"""Notification channels and templates — provider-agnostic identifiers.

Adding a new channel: add a member here + a gateway implementation in infra/.
No domain code changes required for new providers (ADR-009).
"""
from __future__ import annotations

from enum import Enum


class NotificationChannel(str, Enum):
    SMS       = "SMS"
    EMAIL     = "EMAIL"
    WHATSAPP  = "WHATSAPP"
    PUSH      = "PUSH"


class NotificationTemplate(str, Enum):
    """Logical template identifiers — resolved to provider-specific content by the gateway."""
    ORDER_CONFIRMED    = "ORDER_CONFIRMED"     # sent when Order moves to CONFIRMED
    ORDER_CANCELLED    = "ORDER_CANCELLED"     # sent when Order is CANCELLED
    REFUND_INITIATED   = "REFUND_INITIATED"    # sent when intent enters REFUND_PENDING
    RESERVATION_EXPIRY = "RESERVATION_EXPIRY"  # optional: warn customer before expiry
