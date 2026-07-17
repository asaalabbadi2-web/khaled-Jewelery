"""Contract tests for NotificationWorker.

Tests the run_once() dispatch loop using a mock SQLAlchemy session.
No real database, no network. Gateway and session are pure stubs.

Gate coverage:
  N1: OrderCreated event + customer_phone  → SMS dispatched, session committed
  N2: Missing customer_phone               → event marked, no notification sent
  N3: Missing reservation row              → event marked, no notification sent
  N4: Empty queue                          → returns 0, no commit
  N5: Idempotency — already sent           → gateway not called twice
  N6: Gateway failure                      → FAILED notification saved, no raise
  N7: UniqueConstraint race                → worker survives + cursor advances (Law 0)
  N8: Idempotency key snapshot             → exact bytes pinned as external contract
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from yasargold_domain.notifications.channels import NotificationChannel, NotificationTemplate
from yasargold_domain.notifications.exceptions import NotificationGatewayError

from yasargold_commerce.workers.notification_worker import NotificationWorker

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ORDER_ID = "ord_nw_contract_001"
_RES_ID = "res_nw_contract_001"
_PHONE = "+966501234567"
_NOW = datetime.now(timezone.utc).replace(microsecond=0)


# ---------------------------------------------------------------------------
# Stubs — ORM-row-like dataclasses
# ---------------------------------------------------------------------------

def _default_payload() -> str:
    return json.dumps({
        "order_id": _ORDER_ID,
        "reservation_id": _RES_ID,
        "amount": "5500.00",
        "currency": "SAR",
    })


@dataclass
class _StubOutboxRow:
    id: int = 1
    event_type: str = "OrderCreated"
    payload: str = field(default_factory=_default_payload)
    created_at: datetime = field(default_factory=lambda: _NOW)
    notification_dispatched_at: datetime | None = None


@dataclass
class _StubResRow:
    id: str = _RES_ID
    customer_phone: str | None = _PHONE


@dataclass
class _StubNotificationRow:
    """Mimics a NotificationRow for seeding prior notifications in idempotency tests."""
    id: str = "ntf_prior_001"
    order_id: str = _ORDER_ID
    channel: str = "SMS"
    recipient: str = _PHONE
    template: str = "ORDER_CONFIRMED"
    status: str = "SENT"
    created_at: datetime = field(default_factory=lambda: _NOW)
    sent_at: datetime | None = None
    failure_reason: str | None = None


# ---------------------------------------------------------------------------
# Mock session
# ---------------------------------------------------------------------------

class _MultiFnResult:
    """Supports both .scalars().all() and .scalar_one_or_none() call chains."""

    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalars(self) -> _MultiFnResult:
        return self

    def all(self) -> list:
        return self._rows

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None


class _MockSession:
    def __init__(
        self,
        outbox_rows: list | None = None,
        res_row: Any = None,
        no_res_row: bool = False,
        prior_notifications: list | None = None,
    ) -> None:
        self._outbox_rows = outbox_rows if outbox_rows is not None else [_StubOutboxRow()]
        self._res_row = None if no_res_row else (res_row if res_row is not None else _StubResRow())
        self._prior_notifications: list = prior_notifications or []
        self.added_notifications: list = []
        self.commit_count: int = 0
        self.closed: bool = False

    def execute(self, stmt: Any) -> _MultiFnResult:
        from yasargold_commerce.infra.notification_orm import NotificationRow
        from yasargold_commerce.infra.reservation_orm import OutboxEventRow, ReservationRow

        try:
            entity = stmt.column_descriptions[0]["entity"]
            if entity is OutboxEventRow:
                return _MultiFnResult(self._outbox_rows)
            if entity is ReservationRow:
                rows = [self._res_row] if self._res_row is not None else []
                return _MultiFnResult(rows)
            if entity is NotificationRow:
                return _MultiFnResult(self._prior_notifications)
        except (AttributeError, IndexError, KeyError):
            pass
        # UPDATE statement — no result consumed by caller
        return _MultiFnResult([])

    def get(self, model: type, id_: str) -> Any:
        for n in self._prior_notifications:
            if n.id == id_:
                return n
        return None

    def add(self, obj: Any) -> None:
        from yasargold_commerce.infra.notification_orm import NotificationRow
        if isinstance(obj, NotificationRow):
            self.added_notifications.append(obj)

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class _MockSessionFactory:
    def __init__(self, session: _MockSession) -> None:
        self._session = session

    def __call__(self) -> _MockSession:
        return self._session


class _StubGateway:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[dict] = []
        self._fail = fail

    def send(
        self,
        channel: NotificationChannel,
        recipient: str,
        template: NotificationTemplate,
        variables: dict,
        idempotency_key: str | None = None,
    ) -> str:
        self.calls.append({"channel": channel, "recipient": recipient, "idempotency_key": idempotency_key})
        if self._fail:
            raise NotificationGatewayError(channel.value, "gateway timeout")
        return "ref_sms_001"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_worker(
    session: _MockSession,
    fail: bool = False,
) -> tuple[NotificationWorker, _StubGateway]:
    gw = _StubGateway(fail=fail)
    return NotificationWorker(_MockSessionFactory(session), gw), gw


# ---------------------------------------------------------------------------
# N1: Happy path — OrderCreated event + customer_phone
# ---------------------------------------------------------------------------

class TestN1HappyPath:
    def test_dispatches_sms_notification(self) -> None:
        session = _MockSession()
        worker, _ = _make_worker(session)
        worker.run_once()
        assert len(session.added_notifications) == 1
        assert session.added_notifications[0].channel == "SMS"

    def test_notification_template_is_order_confirmed(self) -> None:
        session = _MockSession()
        worker, _ = _make_worker(session)
        worker.run_once()
        assert session.added_notifications[0].template == "ORDER_CONFIRMED"

    def test_notification_recipient_matches_customer_phone(self) -> None:
        session = _MockSession()
        worker, _ = _make_worker(session)
        worker.run_once()
        assert session.added_notifications[0].recipient == _PHONE

    def test_notification_order_id_matches_event_payload(self) -> None:
        session = _MockSession()
        worker, _ = _make_worker(session)
        worker.run_once()
        assert session.added_notifications[0].order_id == _ORDER_ID

    def test_notification_status_is_sent(self) -> None:
        session = _MockSession()
        worker, _ = _make_worker(session)
        worker.run_once()
        assert session.added_notifications[0].status == "SENT"

    def test_gateway_called_once(self) -> None:
        session = _MockSession()
        worker, gw = _make_worker(session)
        worker.run_once()
        assert len(gw.calls) == 1

    def test_session_committed(self) -> None:
        session = _MockSession()
        worker, _ = _make_worker(session)
        worker.run_once()
        # Inner commit (uow.commit()) + outer commit (batch marker)
        assert session.commit_count >= 1

    def test_run_once_returns_1(self) -> None:
        session = _MockSession()
        worker, _ = _make_worker(session)
        assert worker.run_once() == 1

    def test_idempotency_key_passed_to_gateway(self) -> None:
        # ADR-014 §Atomicity: key must be stable across retries
        session = _MockSession()
        worker, gw = _make_worker(session)
        worker.run_once()
        key = gw.calls[0]["idempotency_key"]
        assert key is not None
        assert _ORDER_ID in key
        assert "ORDER_CONFIRMED" in key
        assert "SMS" in key


# ---------------------------------------------------------------------------
# N2: Missing customer_phone — event marked but no notification sent
# ---------------------------------------------------------------------------

class TestN2MissingPhone:
    def test_no_notification_added(self) -> None:
        session = _MockSession(res_row=_StubResRow(customer_phone=None))
        worker, _ = _make_worker(session)
        worker.run_once()
        assert len(session.added_notifications) == 0

    def test_gateway_not_called(self) -> None:
        session = _MockSession(res_row=_StubResRow(customer_phone=None))
        worker, gw = _make_worker(session)
        worker.run_once()
        assert len(gw.calls) == 0

    def test_event_still_marked_dispatched(self) -> None:
        # Outer commit fires to advance the cursor even when notification is skipped
        session = _MockSession(res_row=_StubResRow(customer_phone=None))
        worker, _ = _make_worker(session)
        worker.run_once()
        assert session.commit_count >= 1

    def test_run_once_returns_1(self) -> None:
        # Event counted as processed (cursor advanced), not as notification sent
        session = _MockSession(res_row=_StubResRow(customer_phone=None))
        worker, _ = _make_worker(session)
        assert worker.run_once() == 1


# ---------------------------------------------------------------------------
# N3: Missing reservation row
# ---------------------------------------------------------------------------

class TestN3MissingReservation:
    def test_no_notification_added(self) -> None:
        session = _MockSession(no_res_row=True)
        worker, _ = _make_worker(session)
        worker.run_once()
        assert len(session.added_notifications) == 0

    def test_gateway_not_called(self) -> None:
        session = _MockSession(no_res_row=True)
        worker, gw = _make_worker(session)
        worker.run_once()
        assert len(gw.calls) == 0

    def test_run_once_returns_1(self) -> None:
        session = _MockSession(no_res_row=True)
        worker, _ = _make_worker(session)
        assert worker.run_once() == 1


# ---------------------------------------------------------------------------
# N4: Empty queue
# ---------------------------------------------------------------------------

class TestN4EmptyQueue:
    def test_returns_0(self) -> None:
        session = _MockSession(outbox_rows=[])
        worker, _ = _make_worker(session)
        assert worker.run_once() == 0

    def test_no_commit_when_queue_empty(self) -> None:
        session = _MockSession(outbox_rows=[])
        worker, _ = _make_worker(session)
        worker.run_once()
        assert session.commit_count == 0

    def test_gateway_not_called(self) -> None:
        session = _MockSession(outbox_rows=[])
        worker, gw = _make_worker(session)
        worker.run_once()
        assert len(gw.calls) == 0


# ---------------------------------------------------------------------------
# N5: Idempotency — ORDER_CONFIRMED SMS already recorded for this order
# ---------------------------------------------------------------------------

class TestN5Idempotency:
    def test_no_notification_added_when_already_sent(self) -> None:
        prior = _StubNotificationRow()
        session = _MockSession(prior_notifications=[prior])
        worker, _ = _make_worker(session)
        worker.run_once()
        assert len(session.added_notifications) == 0

    def test_gateway_not_called_when_already_sent(self) -> None:
        prior = _StubNotificationRow()
        session = _MockSession(prior_notifications=[prior])
        worker, gw = _make_worker(session)
        worker.run_once()
        assert len(gw.calls) == 0

    def test_event_still_marked_dispatched(self) -> None:
        prior = _StubNotificationRow()
        session = _MockSession(prior_notifications=[prior])
        worker, _ = _make_worker(session)
        worker.run_once()
        # Outer batch commit still fires — cursor advances
        assert session.commit_count >= 1


# ---------------------------------------------------------------------------
# N6: Gateway failure — FAILED notification saved, run_once does not raise
# ---------------------------------------------------------------------------

class TestN6GatewayFailure:
    def test_failed_notification_saved(self) -> None:
        session = _MockSession()
        worker, _ = _make_worker(session, fail=True)
        worker.run_once()
        assert len(session.added_notifications) == 1
        assert session.added_notifications[0].status == "FAILED"

    def test_failure_reason_recorded(self) -> None:
        session = _MockSession()
        worker, _ = _make_worker(session, fail=True)
        worker.run_once()
        assert session.added_notifications[0].failure_reason == "gateway timeout"

    def test_run_once_does_not_raise_on_gateway_error(self) -> None:
        session = _MockSession()
        worker, _ = _make_worker(session, fail=True)
        count = worker.run_once()
        assert count == 1


# ---------------------------------------------------------------------------
# N7: UniqueConstraint race — DB constraint is the second defence (Law 0)
# ---------------------------------------------------------------------------

class _IntegrityErrorSession(_MockSession):
    """Simulates a unique constraint violation on the inner uow.commit().

    The first commit() call raises SAIntegrityError (mimics DB rejecting a
    duplicate row). Subsequent commits (outer batch cursor advance) succeed.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._first_commit_fired = False

    def commit(self) -> None:
        if not self._first_commit_fired:
            self._first_commit_fired = True
            from sqlalchemy.exc import IntegrityError as SAIntegrityError
            raise SAIntegrityError(
                "INSERT INTO notifications",
                {},
                Exception("UNIQUE constraint failed: notifications.uq_notifications_order_template_channel"),
            )
        self.commit_count += 1

    def rollback(self) -> None:
        pass


class TestN7UniqueConstraintRace:
    def test_worker_survives_integrity_error(self) -> None:
        # IntegrityError must not propagate out of run_once()
        session = _IntegrityErrorSession()
        worker, _ = _make_worker(session)
        count = worker.run_once()  # must not raise
        assert count == 1

    def test_cursor_advances_after_integrity_error(self) -> None:
        # The event must NOT re-queue forever — outer commit must fire
        session = _IntegrityErrorSession()
        worker, _ = _make_worker(session)
        worker.run_once()
        # Inner commit raised; outer commit succeeded (commit_count == 1)
        assert session.commit_count >= 1


# ---------------------------------------------------------------------------
# N8: Idempotency key snapshot — external contract with SMS provider
# ---------------------------------------------------------------------------

class TestN8IdempotencyKeySnapshot:
    def test_key_literal_form_for_worker(self) -> None:
        # Pin the exact bytes passed to the provider.
        # Any change silently opens the duplicate-send window at the provider.
        # Template and channel use .value (enum string), not repr() or class name.
        session = _MockSession()
        worker, gw = _make_worker(session)
        worker.run_once()
        assert gw.calls[0]["idempotency_key"] == f"{_ORDER_ID}:ORDER_CONFIRMED:SMS"
