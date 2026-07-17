# ADR-014: Notifications — Provider-Agnostic Domain with Adapter Injection

**Status:** Accepted  
**Date:** 2026-07-14

---

## Rule

Notification dispatch logic lives in the domain (`yasargold_domain.notifications`).  
The delivery channel (SMS, WhatsApp, email) is an injected adapter conforming to `NotificationGateway`.  
No provider SDK is imported by the domain package.

---

## Context

Sprint 6 added customer notifications for the Order Confirmed event. The immediate need is SMS via a provider TBD (Unifonic, Twilio, or local carrier). Three questions drove the design:

1. **Can we swap SMS providers without touching domain logic?**
2. **Can we add WhatsApp or push notifications without branching business rules?**
3. **Can we test notification logic without a live SMS provider account?**

All three answers must be "yes" before releasing to production.

---

## Decision

### Domain package (`yasargold_domain.notifications`)

| File | Responsibility |
|---|---|
| `channels.py` | `NotificationChannel` enum (SMS / EMAIL / WHATSAPP / PUSH) and `NotificationTemplate` enum |
| `notification.py` | `Notification` aggregate — status machine (PENDING → SENT / FAILED) |
| `gateway.py` | `NotificationGateway` Protocol — one method: `send(channel, recipient, template, variables) → provider_reference` |
| `service.py` | `NotificationService` — `dispatch()` and `dispatch_all()` |
| `repository.py` | `NotificationRepository` + `NotificationUnitOfWork` Protocols |

**`dispatch()` contract:**
- Builds a PENDING `Notification`
- Calls `gateway.send()` — if it raises `NotificationGatewayError`, records FAILED and saves
- Never raises to caller (failure is a fact, not an exception) — consistent with ADR-008

**`dispatch_all()` contract:**
- Calls `dispatch()` per channel independently
- One channel failure does not block others
- Returns `list[Notification]` (facts, not count) — consistent with ADR-008

### Infrastructure (`apps/commerce-api`)

| File | Responsibility |
|---|---|
| `notification_orm.py` | `NotificationRow` SQLAlchemy mapped class |
| `notification_store.py` | `SQLAlchemyNotificationRepository` |
| `notification_uow.py` | `SQLAlchemyNotificationUnitOfWork` |
| `log_notification_gateway.py` | `LogNotificationGateway` — logs and returns a fake ref (staging / local dev) |

### Worker (`NotificationWorker`)

Polls `outbox_events` for `event_type='OrderCreated'` with `notification_dispatched_at IS NULL`.

Cursor: `notification_dispatched_at` on `outbox_events` — independent of `published_at` (OutboxWorker's cursor). Each worker drains its own view of the same table (ADR-007 pattern).

**Cursor commit is separate from notification commit** — intentionally. The inner `uow.commit()` persists the `Notification` row (SENT or FAILED). The outer `session.commit()` advances the cursor. Two commits on the same connection means a crash between them leaves the notification persisted but the cursor not advanced. On restart the idempotency guard finds the persisted notification → skips → cursor advances. This is safe.

Idempotency guard: queries `notifications` by `order_id + template + channel` before dispatching. Guard happens at read time; `FOR UPDATE SKIP LOCKED` on the outbox row ensures only one worker processes each event concurrently. There is no DB-level unique constraint on `(order_id, template, channel)` — this is a known gap, acceptable while worker instances remain single-threaded. Add the constraint when moving to multi-replica deployment.

Delivery guarantee: at-least-once for event processing. Gateway delivery is exactly-once-or-fail: if `NotificationGateway.send()` raises, the notification is recorded as `FAILED` and the cursor still advances (see retry policy below).

### Failure and retry policy (explicit decision)

`dispatch()` never raises. A `NotificationGatewayError` from the provider is caught, recorded as a `FAILED` Notification fact, and the event cursor advances. This means:

**A failed gateway call produces a terminal `FAILED` notification — it is not retried automatically.**

This is a deliberate tradeoff:
- Pro: worker stays alive; a broken SMS provider does not stall order processing
- Con: the customer does not receive the notification; this is silent failure unless observed

**Required observability (enforcement):**
- Prometheus counter `notifications_failed_total{template, channel}` — must be emitted in the production SMS adapter and in `NotificationService`
- Alert rule: `notifications_failed_total` rate > 0.01/min for 5 minutes → PagerDuty
- Without this counter and alert, the never-raises contract is a data-loss risk

**Retry path (Sprint 6 deferred):** If the alert fires and the failed notifications need to be replayed, the operational procedure is: query `SELECT * FROM notifications WHERE status='FAILED'` and re-run the worker targeting those order IDs. A retry queue with `attempt_count` + `next_retry_at` is planned but out of scope for Sprint 6. This ADR must be superseded by ADR-01x before enabling a high-volume SMS provider.

**What this ADR does NOT permit:** silently discarding FAILED notifications without an observable signal. If the observability requirement above is not met, this design is not safe to ship with a real SMS provider.

### customer_phone on Reservation

`ReservationRecord.customer_phone: str | None` — captured at reservation creation and stored in `reservations.customer_phone`. The NotificationWorker reads it from the DB when an OrderCreated event arrives.

This avoids embedding PII in outbox payloads (ADR-007: events carry IDs, not denormalized data).

---

## Alternatives Considered

### Option A: Embed provider SDK in router/worker

Simpler initially; provider-specific logic bleeds into business code. Swapping providers requires touching domain tests. Rejected.

### Option B: Notification as a separate microservice

Full isolation; overkill for current volume. Adds a network hop and an operational surface. Revisit post-Gate B. Rejected for now.

### Option C (chosen): Adapter injection with domain protocol

Gateway is a Protocol (`typing.Protocol`) — no abstract base class, no framework coupling. Domain tests inject a `_StubGateway`. Production injects a real SMS adapter at worker startup.

---

## Atomicity Gap and Claim-Then-Send Requirement

The current `dispatch()` call path has a known atomicity gap:

```
gateway.send()  ← network call — provider ACKs, SMS delivered
[crash here]
uow.commit()    ← never reached — no SENT row written
```

On worker restart, `find_by_order_id()` finds no notification, `already_sent = False` → sends again → customer receives duplicate.

**Closure for this gap:** the provider's idempotency key. Every call to `gateway.send()` MUST include an `idempotency_key = f"{order_id}:{template.value}:{channel.value}"`. Providers that support idempotency (Twilio, Unifonic) deduplicate on their side and return the same provider reference. This is the only mechanism that prevents a duplicate send — no local transaction can span a network call.

**Before enabling a real SMS adapter, the worker MUST switch to claim-then-send:**

```python
# Phase 1: Claim (atomic — commit PENDING before network call)
with uow:
    pending = service.claim(order_id, channel, recipient, template, now, uow)
    uow.commit()                    # PENDING row is now visible; crash → orphaned PENDING = detectable gap

# Phase 2: Send (outside any transaction guarantee)
try:
    provider_ref = gateway.send(..., idempotency_key=key)
    success, data = True, provider_ref
except NotificationGatewayError as e:
    success, data = False, e.reason

# Phase 3: Mark result (atomic)
with uow:
    service.mark_result(pending, success, data, now, uow)
    uow.commit()                    # SENT or FAILED
```

`NotificationService.claim()` and `mark_result()` are already implemented. The worker currently uses the single-commit `dispatch()` path, which is acceptable ONLY with `LogNotificationGateway`. Switching to claim-then-send is a prerequisite for any production SMS adapter and must be done in the same sprint as the adapter, not after.

A PENDING row that is never updated to SENT/FAILED (orphaned) is a detectable signal of the crash window. A monitoring query over `notifications WHERE status='PENDING' AND created_at < now() - interval '10 minutes'` can alert on this condition.

**DB-level idempotency:** `notifications(order_id, template, channel)` has a `UNIQUE` constraint (`uq_notifications_order_template_channel`). This enforces the "no duplicate notification" invariant at two levels: application guard (`find_by_order_id`) and database constraint. The DB constraint also protects manual maintenance paths and future resend scripts that bypass the application guard.

---

## Error Classification and Retry Policy

`dispatch()` never raises. `NotificationGatewayError` is caught and produces a terminal `FAILED` notification. However, not all gateway errors are equal:

| Error type | Examples | Current handling | Recommended handling |
|------------|----------|-----------------|---------------------|
| **Permanent** | Invalid phone (E.164), rejected template, account suspended | FAILED immediately ✓ | FAILED immediately |
| **Transient** | Provider timeout, 5xx, rate limit 429 | FAILED immediately — **too harsh** | ≤3 retries with exponential backoff, then FAILED |

**Current decision for Sprint 6:** All errors produce terminal FAILED. Acceptable because:
1. We are using `LogNotificationGateway` — no real sends
2. An ORDER_CONFIRMED notification is customer-service-recoverable — staff can resend manually if alerted

**Required before real SMS adapter:** Gateway adapter MUST classify errors as transient or permanent and expose `is_transient: bool` on `NotificationGatewayError`. `NotificationService` or the worker retry loop can then decide on retries.

**Manual resend runbook (operational procedure for FAILED notifications):**
Until automated retry exists, the procedure when `notifications_failed_total` alert fires:
1. Query: `SELECT order_id, template, channel, failure_reason, created_at FROM notifications WHERE status = 'FAILED' ORDER BY created_at DESC LIMIT 50`
2. For permanent errors (invalid phone, template issue): escalate to customer service — do not resend automatically
3. For transient errors (timeout, 5xx): reset status to PENDING → `UPDATE notifications SET status = 'PENDING', failure_reason = NULL WHERE id IN (...)`; next worker tick will re-attempt
4. Confirm with Prometheus that `notifications_sent_total` rises after reset

This runbook section becomes obsolete once retry infrastructure is in place.

---

## Consequences

**Positive:**
- Domain notification tests run with zero network calls
- Adding a real SMS provider = write one class implementing `NotificationGateway` and inject it
- WhatsApp or email channels = add an enum value and an adapter; no domain changes
- `dispatch()` never raises — callers always get a `Notification` fact, consistent with ADR-008
- `notifications(order_id, template, channel)` UNIQUE constraint enforces the no-duplicate invariant at two levels

**Negative:**
- `customer_phone` is stored in the `reservations` table — coupling notification routing to the reservation aggregate. Acceptable for v1; revisit if customer profile becomes a standalone domain.
- `dispatch()` has a crash-window atomicity gap (send succeeds, commit fails). Mitigated by provider idempotency key. Eliminated by claim-then-send (required before real SMS adapter).
- FAILED is terminal in the current design — transient errors are not retried. Acceptable with LogNotificationGateway; must be resolved before production SMS adapter.

---

## References

- ADR-007: Domain events as first-class citizens (outbox pattern)
- ADR-008: Domain returns facts not statistics (`dispatch()` returns `Notification`, not bool)
- ADR-009: External providers are adapters (`NotificationGateway` Protocol)
