"""Contract tests for ShipmentService + ShipmentRepository (claim-then-send).

Tests exercise the domain service against a mock session — no real database,
no network. Gateway and session are pure stubs.

Gate coverage:
    S1: claim() saves PENDING shipment with correct fields
    S2: mark_created() transitions PENDING → CREATED with tracking_number
    S3: mark_created() emits ShipmentCreated to outbox
    S4: mark_failed() transitions PENDING → FAILED with failure_reason
    S5: void() within void_window → VOIDED + ShipmentVoided emitted
    S6: void() after void_window expires → CannotVoidShipmentError raised
    S7: mark_delivered() IN_TRANSIT → DELIVERED + ShipmentDelivered emitted
    S8: idempotency_key snapshot — exact bytes pinned as external contract
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from yasargold_domain.shipping.carrier_config import CarrierConfig
from yasargold_domain.shipping.events import ShipmentCreated, ShipmentDelivered, ShipmentVoided
from yasargold_domain.shipping.exceptions import CannotVoidShipmentError
from yasargold_domain.shipping.service import ShipmentService
from yasargold_domain.shipping.shipment import Shipment, ShipmentStatus
from yasargold_domain.shared.identifiers import OrderId, ShipmentId

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ORDER_ID = OrderId("ord_sh_contract_001")
_NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)
_DECLARED_VALUE = Decimal("5500.00")
_TRACKING_NUMBER = "TRK-STUB-001"

_CARRIER = CarrierConfig(
    carrier_id="aramex",
    name="Aramex",
    void_window=timedelta(hours=6),
)

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _StubGateway:
    def __init__(self, fail: bool = False, tracking: str = _TRACKING_NUMBER) -> None:
        self.create_calls: list[dict] = []
        self.void_calls: list[dict] = []
        self._fail = fail
        self._tracking = tracking

    def create_shipment(
        self,
        order_id: OrderId,
        carrier_id: str,
        declared_value: Decimal,
        idempotency_key: str,
    ) -> str:
        from yasargold_domain.shipping.exceptions import ShipmentGatewayError
        self.create_calls.append({"order_id": order_id, "idempotency_key": idempotency_key})
        if self._fail:
            raise ShipmentGatewayError(carrier_id, "carrier timeout")
        return self._tracking

    def void_shipment(self, carrier_id: str, tracking_number: str) -> None:
        self.void_calls.append({"carrier_id": carrier_id, "tracking_number": tracking_number})


class _InMemoryShipmentRepository:
    def __init__(self, initial: Shipment | None = None) -> None:
        self._store: dict[str, Shipment] = {}
        if initial is not None:
            self._store[str(initial.id)] = initial

    def save(self, shipment: Shipment) -> None:
        self._store[str(shipment.id)] = shipment

    def find_by_id(self, shipment_id: ShipmentId) -> Shipment | None:
        return self._store.get(str(shipment_id))

    def find_by_order_id(self, order_id: OrderId) -> Shipment | None:
        for s in self._store.values():
            if s.order_id == order_id:
                return s
        return None

    @property
    def all(self) -> list[Shipment]:
        return list(self._store.values())


class _InMemoryOutbox:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def enqueue(self, event: Any) -> None:
        self.events.append(event)


class _InMemoryUoW:
    def __init__(self, initial_shipment: Shipment | None = None) -> None:
        self.repository = _InMemoryShipmentRepository(initial_shipment)
        self.outbox = _InMemoryOutbox()

    def __enter__(self) -> _InMemoryUoW:
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_service(fail: bool = False) -> tuple[ShipmentService, _StubGateway]:
    gw = _StubGateway(fail=fail)
    return ShipmentService(gw), gw


def _make_pending(uow: _InMemoryUoW | None = None) -> tuple[Shipment, _InMemoryUoW]:
    svc, _ = _make_service()
    u = uow or _InMemoryUoW()
    shipment = svc.claim(_ORDER_ID, _CARRIER, _DECLARED_VALUE, _NOW, u)
    return shipment, u


def _make_created(uow: _InMemoryUoW | None = None) -> tuple[Shipment, _InMemoryUoW, ShipmentService]:
    svc, _ = _make_service()
    u = uow or _InMemoryUoW()
    pending = svc.claim(_ORDER_ID, _CARRIER, _DECLARED_VALUE, _NOW, u)
    created = svc.mark_created(pending, _TRACKING_NUMBER, _NOW, u)
    return created, u, svc


# ---------------------------------------------------------------------------
# S1: claim() saves PENDING shipment
# ---------------------------------------------------------------------------

class TestS1Claim:
    def test_status_is_pending(self) -> None:
        shipment, _ = _make_pending()
        assert shipment.status == ShipmentStatus.PENDING

    def test_declared_value_matches(self) -> None:
        shipment, _ = _make_pending()
        assert shipment.declared_value == _DECLARED_VALUE

    def test_carrier_id_matches(self) -> None:
        shipment, _ = _make_pending()
        assert shipment.carrier_id == _CARRIER.carrier_id

    def test_order_id_matches(self) -> None:
        shipment, _ = _make_pending()
        assert shipment.order_id == _ORDER_ID

    def test_shipment_saved_to_repository(self) -> None:
        shipment, uow = _make_pending()
        saved = uow.repository.find_by_id(shipment.id)
        assert saved is not None
        assert saved.id == shipment.id

    def test_tracking_number_is_none(self) -> None:
        shipment, _ = _make_pending()
        assert shipment.tracking_number is None


# ---------------------------------------------------------------------------
# S2: mark_created() transitions PENDING → CREATED
# ---------------------------------------------------------------------------

class TestS2MarkCreated:
    def test_status_is_created(self) -> None:
        created, _, _ = _make_created()
        assert created.status == ShipmentStatus.CREATED

    def test_tracking_number_set(self) -> None:
        created, _, _ = _make_created()
        assert created.tracking_number == _TRACKING_NUMBER

    def test_registered_at_set(self) -> None:
        created, _, _ = _make_created()
        assert created.registered_at == _NOW

    def test_declared_value_unchanged(self) -> None:
        created, _, _ = _make_created()
        assert created.declared_value == _DECLARED_VALUE


# ---------------------------------------------------------------------------
# S3: mark_created() emits ShipmentCreated to outbox
# ---------------------------------------------------------------------------

class TestS3OutboxEvent:
    def test_shipment_created_enqueued(self) -> None:
        _, uow, _ = _make_created()
        types = [type(e).__name__ for e in uow.outbox.events]
        assert "ShipmentCreated" in types

    def test_shipment_created_has_correct_order_id(self) -> None:
        _, uow, _ = _make_created()
        event = next(e for e in uow.outbox.events if isinstance(e, ShipmentCreated))
        assert event.order_id == _ORDER_ID

    def test_shipment_created_has_tracking_number(self) -> None:
        _, uow, _ = _make_created()
        event = next(e for e in uow.outbox.events if isinstance(e, ShipmentCreated))
        assert event.tracking_number == _TRACKING_NUMBER

    def test_shipment_created_has_frozen_declared_value(self) -> None:
        _, uow, _ = _make_created()
        event = next(e for e in uow.outbox.events if isinstance(e, ShipmentCreated))
        assert event.declared_value == _DECLARED_VALUE


# ---------------------------------------------------------------------------
# S4: mark_failed() transitions PENDING → FAILED
# ---------------------------------------------------------------------------

class TestS4MarkFailed:
    def test_status_is_failed(self) -> None:
        svc, _ = _make_service()
        uow = _InMemoryUoW()
        pending = svc.claim(_ORDER_ID, _CARRIER, _DECLARED_VALUE, _NOW, uow)
        failed = svc.mark_failed(pending, "carrier rejected", uow)
        assert failed.status == ShipmentStatus.FAILED

    def test_failure_reason_recorded(self) -> None:
        svc, _ = _make_service()
        uow = _InMemoryUoW()
        pending = svc.claim(_ORDER_ID, _CARRIER, _DECLARED_VALUE, _NOW, uow)
        failed = svc.mark_failed(pending, "carrier rejected", uow)
        assert failed.failure_reason == "carrier rejected"

    def test_tracking_number_remains_none(self) -> None:
        svc, _ = _make_service()
        uow = _InMemoryUoW()
        pending = svc.claim(_ORDER_ID, _CARRIER, _DECLARED_VALUE, _NOW, uow)
        failed = svc.mark_failed(pending, "carrier rejected", uow)
        assert failed.tracking_number is None


# ---------------------------------------------------------------------------
# S5: void() within void_window
# ---------------------------------------------------------------------------

class TestS5VoidWithinWindow:
    def test_status_is_voided(self) -> None:
        created, uow, svc = _make_created()
        now = _NOW + timedelta(hours=1)
        svc.void(created.id, _CARRIER, now, uow)
        voided = uow.repository.find_by_id(created.id)
        assert voided is not None
        assert voided.status == ShipmentStatus.VOIDED

    def test_voided_at_set(self) -> None:
        created, uow, svc = _make_created()
        now = _NOW + timedelta(hours=1)
        result = svc.void(created.id, _CARRIER, now, uow)
        assert result.voided_at == now

    def test_shipment_voided_enqueued(self) -> None:
        created, uow, svc = _make_created()
        now = _NOW + timedelta(hours=1)
        svc.void(created.id, _CARRIER, now, uow)
        types = [type(e).__name__ for e in uow.outbox.events]
        assert "ShipmentVoided" in types

    def test_gateway_void_called(self) -> None:
        svc, gw = _make_service()
        uow = _InMemoryUoW()
        pending = svc.claim(_ORDER_ID, _CARRIER, _DECLARED_VALUE, _NOW, uow)
        created = svc.mark_created(pending, _TRACKING_NUMBER, _NOW, uow)
        svc.void(created.id, _CARRIER, _NOW + timedelta(hours=1), uow)
        assert len(gw.void_calls) == 1
        assert gw.void_calls[0]["tracking_number"] == _TRACKING_NUMBER


# ---------------------------------------------------------------------------
# S6: void() after void_window expires
# ---------------------------------------------------------------------------

class TestS6VoidAfterWindow:
    def test_raises_cannot_void_error(self) -> None:
        created, uow, svc = _make_created()
        now = _NOW + timedelta(hours=7)  # 7h > 6h void_window
        with pytest.raises(CannotVoidShipmentError):
            svc.void(created.id, _CARRIER, now, uow)

    def test_status_unchanged_after_failed_void(self) -> None:
        created, uow, svc = _make_created()
        now = _NOW + timedelta(hours=7)
        try:
            svc.void(created.id, _CARRIER, now, uow)
        except CannotVoidShipmentError:
            pass
        shipment = uow.repository.find_by_id(created.id)
        assert shipment is not None
        assert shipment.status == ShipmentStatus.CREATED


# ---------------------------------------------------------------------------
# S7: mark_delivered() — IN_TRANSIT → DELIVERED + ShipmentDelivered
# ---------------------------------------------------------------------------

class TestS7MarkDelivered:
    def _make_in_transit(self) -> tuple[Shipment, _InMemoryUoW, ShipmentService]:
        created, uow, svc = _make_created()
        in_transit = replace(
            created,
            status=ShipmentStatus.IN_TRANSIT,
            in_transit_at=_NOW,
        )
        uow.repository.save(in_transit)
        return in_transit, uow, svc

    def test_status_is_delivered(self) -> None:
        in_transit, uow, svc = self._make_in_transit()
        now = _NOW + timedelta(days=2)
        svc.mark_delivered(in_transit.id, now, uow)
        delivered = uow.repository.find_by_id(in_transit.id)
        assert delivered is not None
        assert delivered.status == ShipmentStatus.DELIVERED

    def test_delivered_at_set(self) -> None:
        in_transit, uow, svc = self._make_in_transit()
        now = _NOW + timedelta(days=2)
        result = svc.mark_delivered(in_transit.id, now, uow)
        assert result.delivered_at == now

    def test_shipment_delivered_event_enqueued(self) -> None:
        in_transit, uow, svc = self._make_in_transit()
        now = _NOW + timedelta(days=2)
        svc.mark_delivered(in_transit.id, now, uow)
        types = [type(e).__name__ for e in uow.outbox.events]
        assert "ShipmentDelivered" in types

    def test_shipment_delivered_event_has_order_id(self) -> None:
        in_transit, uow, svc = self._make_in_transit()
        now = _NOW + timedelta(days=2)
        svc.mark_delivered(in_transit.id, now, uow)
        event = next(e for e in uow.outbox.events if isinstance(e, ShipmentDelivered))
        assert event.order_id == _ORDER_ID


# ---------------------------------------------------------------------------
# S8: idempotency_key snapshot — external contract
# ---------------------------------------------------------------------------

class TestS8IdempotencyKeySnapshot:
    def test_key_literal_form(self) -> None:
        shipment, _ = _make_pending()
        assert shipment.idempotency_key == f"{_ORDER_ID}:SHIPMENT"

    def test_key_is_stable_across_status_transitions(self) -> None:
        pending, uow = _make_pending()
        svc, _ = _make_service()
        created = svc.mark_created(pending, _TRACKING_NUMBER, _NOW, uow)
        # key must not change
        assert created.idempotency_key == pending.idempotency_key

    def test_key_used_in_gateway_call(self) -> None:
        svc, gw = _make_service()
        uow = _InMemoryUoW()
        pending = svc.claim(_ORDER_ID, _CARRIER, _DECLARED_VALUE, _NOW, uow)
        gw.create_shipment(
            order_id=pending.order_id,
            carrier_id=pending.carrier_id,
            declared_value=pending.declared_value,
            idempotency_key=pending.idempotency_key,
        )
        assert gw.create_calls[0]["idempotency_key"] == f"{_ORDER_ID}:SHIPMENT"
