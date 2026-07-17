# ADR-008: Domain Service Interfaces Return Facts, Not Statistics

**Status**: Accepted  
**Date**: 2026-07-13

## Rule

Domain service methods that process a collection of entities must return the
affected entities (`list[Entity]`), not a count or other derived statistic
(`int`). Callers derive statistics from the returned collection.

## Context

The original signature of `ReservationExpiryService.expire_elapsed()` was:

```python
def expire_elapsed(...) -> int:
    records = uow.repository.find_elapsed_active(...)
    for record in records:
        uow.repository.update_status(record.id, "EXPIRED")
        uow.outbox.enqueue(ReservationExpired(...))
    return len(records)   # ← statistic, not fact
```

When the infrastructure layer needed to record `reservation_lifetime_seconds`
per expired record, two options appeared:

1. **Re-query after commit** — adds a DB round-trip, breaks atomicity of the
   knowledge (the data may have changed between the service call and the query).
2. **Pass a callback** — leaks infrastructure concerns (metrics, logging) into
   the domain service signature.
3. **Return the records** — the caller already has them; no extra query needed.

Option 3 is the only one that does not require the domain to know about its
callers' concerns, and does not add latency.

## Decision

Domain service methods that operate on a set of entities return that set:

```python
# Before
expired_count: int = expiry_service.expire_elapsed(uow, now=now)

# After
expired: list[ReservationRecord] = expiry_service.expire_elapsed(uow, now=now)
expired_count = len(expired)  # caller derives the statistic
```

The returned list contains the full entity state at the moment of mutation.
Callers use it to:

- Record per-entity metrics (`reservation_lifetime_seconds`)
- Build audit log entries
- Send downstream notifications
- Compose additional writes in the same Unit of Work before commit

## Generalisation

This rule applies to any Domain Service that performs a batch mutation:

| Pattern | Wrong return type | Correct return type |
|---|---|---|
| Expire elapsed reservations | `int` (count expired) | `list[ReservationRecord]` |
| Cancel overdue orders | `int` (count cancelled) | `list[Order]` |
| Reconcile pending transfers | `int` (count reconciled) | `list[Transfer]` |
| Retry failed notifications | `int` (count retried) | `list[Notification]` |

**Exception**: a service that deliberately aggregates (e.g. a report generator
whose output *is* a statistic) may return a statistic. The distinction is intent:
a mutation service returns the mutated objects; an aggregation service returns
the aggregate.

## Consequences

**Callers do not re-query**: the returned entities carry the state at mutation
time, which is the most accurate snapshot without an additional round-trip.

**Infrastructure concerns stay out of the Domain**: metrics, logging, and
notification code live in Workers and HTTP handlers, not in domain services.

**Tests become more expressive**: assertions on `expired[0].reserved_at` are
richer than assertions on `count == 1`.

**Signature is self-documenting**: `list[ReservationRecord]` communicates
"these are the records that changed" in a way that `int` does not.

## Enforcement

Any PR that changes a domain service returning a meaningful collection to return
only `int` or `bool` must be rejected in review citing this ADR. The question
to ask: "Does the caller need to know *which* entities were affected?" If yes,
the return type must include them.
