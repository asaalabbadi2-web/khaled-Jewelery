"""Tests for NotificationService — gateway success, failure, and multi-channel dispatch."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytest

from yasargold_domain.notifications.channels import NotificationChannel, NotificationTemplate
from yasargold_domain.notifications.exceptions import NotificationGatewayError
from yasargold_domain.notifications.notification import Notification, NotificationStatus
from yasargold_domain.notifications.repository import NotificationRepository, NotificationUnitOfWork
from yasargold_domain.notifications.service import NotificationService
from yasargold_domain.shared.identifiers import OrderId

_ORDER_ID = OrderId("ord_svc_test01")
_NOW = datetime(2026, 7, 14, 10, 0, 0, tzinfo=timezone.utc)
_PHONE = "+966501234567"


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _StubGateway:
    def __init__(self, should_fail: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self._fail = should_fail

    def send(
        self,
        channel: NotificationChannel,
        recipient: str,
        template: NotificationTemplate,
        variables: dict[str, str],
        idempotency_key: str | None = None,
    ) -> str:
        self.calls.append({
            "channel": channel,
            "recipient": recipient,
            "template": template,
            "idempotency_key": idempotency_key,
        })
        if self._fail:
            raise NotificationGatewayError(channel.value, "provider timeout")
        return f"ref_{channel.value.lower()}"


@dataclass
class _StubRepo:
    saved: list[Notification] = field(default_factory=list)

    def save(self, n: Notification) -> None:
        self.saved.append(n)

    def find_by_order_id(self, order_id: OrderId) -> list[Notification]:
        return []


@dataclass
class _StubUow:
    repository: _StubRepo = field(default_factory=_StubRepo)
    committed: bool = False

    def __enter__(self) -> _StubUow:
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        pass


def _make_service(fail: bool = False) -> tuple[NotificationService, _StubGateway]:
    gw = _StubGateway(should_fail=fail)
    return NotificationService(gw), gw


# ---------------------------------------------------------------------------
# dispatch() — success path
# ---------------------------------------------------------------------------

class TestDispatchSuccess:
    def test_returns_sent_notification(self) -> None:
        svc, _ = _make_service()
        uow = _StubUow()
        result = svc.dispatch(_ORDER_ID, NotificationChannel.SMS, _PHONE,
                              NotificationTemplate.ORDER_CONFIRMED, {}, uow, _NOW)
        assert result.status == NotificationStatus.SENT

    def test_sent_at_is_populated(self) -> None:
        svc, _ = _make_service()
        uow = _StubUow()
        result = svc.dispatch(_ORDER_ID, NotificationChannel.SMS, _PHONE,
                              NotificationTemplate.ORDER_CONFIRMED, {}, uow, _NOW)
        assert result.sent_at == _NOW

    def test_notification_saved_to_repo(self) -> None:
        svc, _ = _make_service()
        uow = _StubUow()
        svc.dispatch(_ORDER_ID, NotificationChannel.SMS, _PHONE,
                     NotificationTemplate.ORDER_CONFIRMED, {}, uow, _NOW)
        assert len(uow.repository.saved) == 1

    def test_gateway_called_once(self) -> None:
        svc, gw = _make_service()
        uow = _StubUow()
        svc.dispatch(_ORDER_ID, NotificationChannel.SMS, _PHONE,
                     NotificationTemplate.ORDER_CONFIRMED, {}, uow, _NOW)
        assert len(gw.calls) == 1

    def test_gateway_receives_correct_channel(self) -> None:
        svc, gw = _make_service()
        uow = _StubUow()
        svc.dispatch(_ORDER_ID, NotificationChannel.SMS, _PHONE,
                     NotificationTemplate.ORDER_CONFIRMED, {}, uow, _NOW)
        assert gw.calls[0]["channel"] == NotificationChannel.SMS

    def test_default_idempotency_key_is_stable(self) -> None:
        # Key must encode order+template+channel for provider deduplication (ADR-014)
        svc, gw = _make_service()
        uow = _StubUow()
        svc.dispatch(_ORDER_ID, NotificationChannel.SMS, _PHONE,
                     NotificationTemplate.ORDER_CONFIRMED, {}, uow, _NOW)
        key = gw.calls[0]["idempotency_key"]
        assert key == f"{_ORDER_ID}:ORDER_CONFIRMED:SMS"

    def test_caller_supplied_idempotency_key_is_passed_through(self) -> None:
        svc, gw = _make_service()
        uow = _StubUow()
        svc.dispatch(_ORDER_ID, NotificationChannel.SMS, _PHONE,
                     NotificationTemplate.ORDER_CONFIRMED, {}, uow, _NOW,
                     idempotency_key="custom_key_abc")
        assert gw.calls[0]["idempotency_key"] == "custom_key_abc"


# ---------------------------------------------------------------------------
# dispatch() — failure path
# ---------------------------------------------------------------------------

class TestDispatchFailure:
    def test_returns_failed_notification(self) -> None:
        svc, _ = _make_service(fail=True)
        uow = _StubUow()
        result = svc.dispatch(_ORDER_ID, NotificationChannel.SMS, _PHONE,
                              NotificationTemplate.ORDER_CONFIRMED, {}, uow, _NOW)
        assert result.status == NotificationStatus.FAILED

    def test_failure_reason_recorded(self) -> None:
        svc, _ = _make_service(fail=True)
        uow = _StubUow()
        result = svc.dispatch(_ORDER_ID, NotificationChannel.SMS, _PHONE,
                              NotificationTemplate.ORDER_CONFIRMED, {}, uow, _NOW)
        assert result.failure_reason == "provider timeout"

    def test_failed_notification_still_saved(self) -> None:
        svc, _ = _make_service(fail=True)
        uow = _StubUow()
        svc.dispatch(_ORDER_ID, NotificationChannel.SMS, _PHONE,
                     NotificationTemplate.ORDER_CONFIRMED, {}, uow, _NOW)
        assert len(uow.repository.saved) == 1

    def test_dispatch_does_not_raise_on_gateway_error(self) -> None:
        svc, _ = _make_service(fail=True)
        uow = _StubUow()
        # Must not raise — failure is recorded, not propagated
        svc.dispatch(_ORDER_ID, NotificationChannel.SMS, _PHONE,
                     NotificationTemplate.ORDER_CONFIRMED, {}, uow, _NOW)


# ---------------------------------------------------------------------------
# dispatch_all() — multi-channel
# ---------------------------------------------------------------------------

class TestDispatchAll:
    def test_returns_one_result_per_channel(self) -> None:
        svc, _ = _make_service()
        uow = _StubUow()
        channels = [
            (NotificationChannel.SMS, _PHONE),
            (NotificationChannel.WHATSAPP, _PHONE),
        ]
        results = svc.dispatch_all(_ORDER_ID, channels, NotificationTemplate.ORDER_CONFIRMED, {}, uow, _NOW)
        assert len(results) == 2

    def test_one_failure_does_not_block_other_channel(self) -> None:
        class _PartialFailGateway:
            def send(self, channel: NotificationChannel, recipient: str,
                     template: NotificationTemplate, variables: dict[str, str],
                     idempotency_key: str | None = None) -> str:
                if channel == NotificationChannel.SMS:
                    raise NotificationGatewayError("SMS", "down")
                return "ref_whatsapp"

        svc = NotificationService(_PartialFailGateway())
        uow = _StubUow()
        channels = [
            (NotificationChannel.SMS, _PHONE),
            (NotificationChannel.WHATSAPP, _PHONE),
        ]
        results = svc.dispatch_all(_ORDER_ID, channels, NotificationTemplate.ORDER_CONFIRMED, {}, uow, _NOW)
        statuses = {r.channel: r.status for r in results}
        assert statuses[NotificationChannel.SMS] == NotificationStatus.FAILED
        assert statuses[NotificationChannel.WHATSAPP] == NotificationStatus.SENT

    def test_dispatch_all_returns_facts_not_count(self) -> None:
        svc, _ = _make_service()
        uow = _StubUow()
        results = svc.dispatch_all(
            _ORDER_ID,
            [(NotificationChannel.SMS, _PHONE)],
            NotificationTemplate.ORDER_CONFIRMED, {}, uow, _NOW,
        )
        assert isinstance(results, list)
        assert isinstance(results[0], Notification)
