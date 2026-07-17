"""Tests for the Notification aggregate state machine."""
from __future__ import annotations

import pytest
from yasargold_domain.notifications.channels import NotificationChannel, NotificationTemplate
from yasargold_domain.notifications.notification import Notification, NotificationStatus
from yasargold_domain.shared.identifiers import OrderId

_ORDER_ID = OrderId("ord_test0001")


def _make(status: NotificationStatus = NotificationStatus.PENDING) -> Notification:
    return Notification(
        id="ntf_test001",
        order_id=_ORDER_ID,
        channel=NotificationChannel.SMS,
        recipient="+966501234567",
        template=NotificationTemplate.ORDER_CONFIRMED,
        status=status,
    )


class TestNotificationStatus:
    def test_pending_is_not_terminal(self) -> None:
        assert not NotificationStatus.PENDING.is_terminal

    def test_sent_is_terminal(self) -> None:
        assert NotificationStatus.SENT.is_terminal

    def test_failed_is_terminal(self) -> None:
        assert NotificationStatus.FAILED.is_terminal


class TestCanSend:
    def test_pending_can_send(self) -> None:
        assert _make(NotificationStatus.PENDING).can_send()

    def test_sent_cannot_send(self) -> None:
        assert not _make(NotificationStatus.SENT).can_send()

    def test_failed_cannot_send(self) -> None:
        assert not _make(NotificationStatus.FAILED).can_send()


class TestIsTerminal:
    def test_pending_aggregate_not_terminal(self) -> None:
        assert not _make(NotificationStatus.PENDING).is_terminal

    def test_sent_aggregate_is_terminal(self) -> None:
        assert _make(NotificationStatus.SENT).is_terminal

    def test_failed_aggregate_is_terminal(self) -> None:
        assert _make(NotificationStatus.FAILED).is_terminal
