# ADR-007: Domain Events Are First-Class Citizens

**Status**: Accepted  
**Date**: 2026-07-12

## Rule

Any event written to the Outbox must be a typed `DomainEvent` instance defined
in `packages/domain`. Application code must never pass raw `dict` or
application-layer payloads to `ReservationEventOutbox.enqueue()`.

## Context

Without this rule, the Outbox accumulates untyped payloads like:

```python
outbox.enqueue("reservation.created", {
    "id": str(reservation.id),
    "item_id": item_id,
    ...
})
```

This couples the Outbox schema to every call site. When the schema changes,
there is no static contract to break — the mismatch is discovered at runtime
by the Worker, typically in production.

## Decision

Domain Events are typed, immutable dataclasses in
`packages/domain/src/yasargold_domain/reservation/events.py`:

```python
outbox.enqueue(ReservationCreated(
    reservation_id=ReservationId("res_abc"),
    quote_id=QuoteId("qt_xyz"),
    item_id=ItemId(42),
    gold_price_id=GoldPriceId(18452),
    locked_rate_per_gram_24k=Decimal("230.00"),
    pricing_engine_version="v1",
    valid_until=valid_until,
))
```

The Outbox *implementation* (in the application layer) serialises the event.
Domain code never knows about JSON format, topic names, or message brokers.

## Invariants enforced in code

| Property | Mechanism |
|---|---|
| Immutable | `@dataclass(frozen=True)` |
| Unique per occurrence | `event_id: str = field(default_factory=uuid4)` |
| Timestamped | `occurred_at: datetime = field(default_factory=utcnow)` |
| Self-describing | `event_type` property returns fully-qualified class name |
| Idempotent consumers | Consumers deduplicate on `event_id` |

## Consequences

**Changing the message broker** (Kafka → RabbitMQ → SNS) requires changing only
the Outbox implementation — not a single domain event definition.

**Adding a consumer** requires only subscribing to the event type string — no
domain change.

**Breaking changes are visible**: renaming a field in `ReservationCreated` is a
compile-time error at every call site, not a silent runtime mismatch.

## Enforcement

Any PR that passes a raw `dict` to `outbox.enqueue()` must be rejected in
review citing this ADR.
