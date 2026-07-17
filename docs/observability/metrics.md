# Commerce API — Metrics Reference

All metrics are defined in
`apps/commerce-api/src/yasargold_commerce/metrics.py`
and exposed at `GET /metrics` (Prometheus text format).

Naming convention: `<subsystem>_<name>_<unit>`

---

## Reservations

### `reservation_success_total`

| Field | Value |
|---|---|
| Type | Counter |
| Source of truth | HTTP 201 response from `POST /api/v1/reservations` |
| Purpose | Primary success-rate SLI for the reservation capability |
| Interpretation | Monotonically increasing. Rate should track active trading hours. |
| Alert | `rate(reservation_success_total[5m]) == 0` during trading hours — possible service outage |
| Action | Check `/health`, DB connectivity, application logs |

---

### `reservation_conflict_total`

| Field | Value |
|---|---|
| Type | Counter |
| Source of truth | HTTP 409 or `ItemAlreadyReservedException` raised in `lock_item()` or `save_reservation()` |
| Purpose | Measures contention — how often two customers compete for the same item |
| Interpretation | Some conflict is expected (popular items). A spike means either high traffic on few items or a bug in expiry (items stuck ACTIVE). |
| Alert | `rate(reservation_conflict_total[5m]) > rate(reservation_success_total[5m]) * 5` — unusually high conflict ratio |
| Action | Check for ACTIVE reservations past `valid_until` (Expiry Worker backlog), review popular-item distribution |

---

### `reservation_policy_denied_total` (labeled by `reason`)

| Field | Value |
|---|---|
| Type | Counter |
| Labels | `reason`: `QUOTE_EXPIRED` \| `QUOTE_STATUS_INVALID` \| `ITEM_UNAVAILABLE` \| `ITEM_ALREADY_RESERVED` \| `TRADING_HALTED` |
| Source of truth | `CompositePolicy.check()` returning `denied` result |
| Purpose | Diagnose why reservations are being rejected by business rules |
| Interpretation | `QUOTE_STATUS_INVALID` / `TRADING_HALTED` spikes → gold price feed issue. `QUOTE_EXPIRED` → clients waiting too long before submitting. |
| Alert | `rate(reservation_policy_denied_total{reason="TRADING_HALTED"}[5m]) > 0` — gold price feed may be down |
| Action | Check `GoldPrice` table: `SELECT MAX(date) FROM gold_price;` — if stale, investigate feed |

---

### `reservation_expired_total`

| Field | Value |
|---|---|
| Type | Counter |
| Source of truth | `ReservationExpiryService.expire_elapsed()` — incremented per record in `ExpiryWorker` |
| Purpose | Track reservation abandonment rate |
| Interpretation | High rate relative to `reservation_success_total` means customers are reserving but not completing payment. |
| Alert | `rate(reservation_expired_total[1h]) / rate(reservation_success_total[1h]) > 0.5` — more than half of reservations expiring |
| Action | Review UX friction in checkout flow; check if payment gateway has high latency |

---

### `reservation_confirmed_total`

| Field | Value |
|---|---|
| Type | Counter |
| Source of truth | `CheckoutService.confirm()` — Sprint 4 checkout endpoint (not yet wired) |
| Purpose | Conversion rate: reservations that completed payment |
| Interpretation | `confirmed / success` is the conversion rate. Target > 0.8 in normal conditions. |
| Alert | Defined in Sprint 4 after checkout endpoint is live |
| Action | — |

---

### `reservation_lock_duration_seconds`

| Field | Value |
|---|---|
| Type | Histogram |
| Buckets | 1ms, 5ms, 10ms, 25ms, 50ms, 100ms, 250ms, 500ms |
| Source of truth | `SELECT FOR UPDATE NOWAIT` round-trip in `SQLAlchemyInventoryRepository.lock_item()` |
| Purpose | Detect DB contention; P95 is a signal for index health |
| Interpretation | P50 should be < 5ms on a well-indexed table. P95 > 50ms indicates lock pressure or index issues. |
| Alert | `histogram_quantile(0.95, reservation_lock_duration_seconds_bucket) > 0.1` — P95 > 100ms |
| Action | `EXPLAIN ANALYZE` on the `lock_item` query; check `ix_reservations_active_item` usage |

---

## Quote Lifecycle

### `quote_age_seconds`

| Field | Value |
|---|---|
| Type | Histogram |
| Buckets | 5s, 15s, 30s, 60s, 90s, 120s, 180s, 300s |
| Source of truth | `now - gp.date` at the moment a reservation succeeds in `POST /api/v1/reservations` |
| Purpose | Calibrate `FRESH_TTL` (currently 90s) with real traffic data |
| Interpretation | P95 tells you: "95% of accepted reservations used a quote younger than X seconds." If P99 < 45s, the 90s TTL is generous. If P95 > 80s, consider extending it. |
| Alert | Not actionable alone — use for periodic TTL review (monthly) |
| Action | Review `histogram_quantile(0.99, quote_age_seconds_bucket)` at 30-day intervals |

---

### `reservation_lifetime_seconds` (labeled by `outcome`)

| Field | Value |
|---|---|
| Type | Histogram |
| Buckets | 1min, 5min, 10min, 15min, 30min, 60min, 120min |
| Labels | `outcome`: `expired` (from ExpiryWorker) \| `confirmed` (from checkout — Sprint 4) |
| Source of truth | `now - record.reserved_at` at the moment of terminal state transition |
| Purpose | Understand customer behaviour: how long between reservation and decision |
| Interpretation | Bimodal distribution is healthy (quick confirms + long abandons). A unimodal spike at the TTL (15 min) means almost all reservations expire without payment. |
| Alert | Defined after checkout is live (Sprint 4) |
| Action | High `expired` lifetime median → investigate checkout UX or payment gateway latency |

---

## Outbox Worker

### `outbox_events_pending`

| Field | Value |
|---|---|
| Type | Gauge |
| Source of truth | `COUNT(*) FROM outbox_events WHERE published_at IS NULL` (approximate — see note) |
| Purpose | Detect Outbox Worker backlog before it causes downstream delays |
| Interpretation | Should stay near 0 during normal operation. Sustained growth means the Worker is not keeping up with the event rate. |
| Alert | `outbox_events_pending > 100 for 5m` — Worker backlog |
| Action | Check Worker logs; verify Worker process is running; run `SELECT COUNT(*) FROM outbox_events WHERE published_at IS NULL` for the authoritative count |

> **Note — concurrent Workers**: this Gauge is set by each Worker tick with a
> `COUNT(*)` snapshot taken inside the tick's transaction, then decremented
> after commit. With multiple Workers running in parallel, readings may appear
> momentarily stale or interleaved. **Do not use this Gauge for transactional
> correctness checks.** The SQL query above is the authoritative source during
> incident investigation.

---

### `outbox_publish_duration_seconds`

| Field | Value |
|---|---|
| Type | Histogram |
| Buckets | 5ms, 10ms, 25ms, 50ms, 100ms, 250ms, 500ms, 1s, 2.5s |
| Source of truth | Time to call `publish_fn(event_type, payload)` for a single event |
| Purpose | Detect slow downstream transport (HTTP webhook, Kafka, SNS) |
| Interpretation | P99 should match the transport's expected latency. Sudden P99 increase → downstream transport degraded. |
| Alert | `histogram_quantile(0.99, outbox_publish_duration_seconds_bucket) > 2` — P99 > 2s |
| Action | Check the publish target (webhook endpoint, message broker); consider dead-letter queue |

---

### `outbox_batch_size_events`

| Field | Value |
|---|---|
| Type | Histogram |
| Buckets | 1, 5, 10, 25, 50, 100 |
| Source of truth | `len(published_ids)` per `OutboxWorker.run_once()` tick |
| Purpose | Understand Worker throughput and batch saturation |
| Interpretation | If most ticks hit the batch ceiling (50 by default), the Worker is falling behind. Reduce Worker interval or increase `batch_size`. |
| Alert | `histogram_quantile(0.9, outbox_batch_size_events_bucket) >= 50` sustained for 10m |
| Action | Reduce Worker `interval_seconds` or increase `batch_size`; scale to multiple Workers |

---

### `outbox_worker_errors_total`

| Field | Value |
|---|---|
| Type | Counter |
| Source of truth | Exceptions caught in `OutboxWorker.run_once()` — the entire batch is rolled back |
| Purpose | Detect transport or DB failures in the Worker loop |
| Interpretation | Any non-zero rate is worth investigating. Events are not lost (they stay unpublished), but downstream consumers are delayed. |
| Alert | `rate(outbox_worker_errors_total[5m]) > 0` |
| Action | Check Worker logs for exception type; verify DB connectivity and publish target availability |

---

## Expiry Worker

### `expiry_worker_batch_size_reservations`

| Field | Value |
|---|---|
| Type | Histogram |
| Buckets | 0, 1, 5, 10, 25, 50, 100 |
| Source of truth | `len(expired_records)` per `ExpiryWorker.run_once()` tick |
| Purpose | Monitor expiry throughput; detect backlog |
| Interpretation | Normally 0–5 per tick. A sustained high batch size means reservations are expiring faster than the Worker is processing them (or the interval is too long). |
| Alert | `histogram_quantile(0.9, expiry_worker_batch_size_reservations_bucket) >= 100` — hitting batch limit |
| Action | Decrease `ExpiryWorker.interval_seconds`; check for unexpected reservation spike |

---

### `expiry_worker_errors_total`

| Field | Value |
|---|---|
| Type | Counter |
| Source of truth | Exceptions caught in `ExpiryWorker.run_once()` — batch rolled back, retried next tick |
| Purpose | Detect DB failures in the Expiry Worker loop |
| Interpretation | Errors here mean reservations are stuck ACTIVE past their `valid_until`, which blocks the same item from being reserved again. |
| Alert | `rate(expiry_worker_errors_total[5m]) > 0` |
| Action | Check Worker logs; `SELECT COUNT(*) FROM reservations WHERE status = 'ACTIVE' AND valid_until < NOW()` to measure backlog; verify DB connectivity |

---

## Cardinality Summary

| Metric | Labels | Max cardinality |
|---|---|---|
| `reservation_policy_denied_total` | `reason` | 5 (bounded by `ReservationRejectionReason` enum) |
| `reservation_lifetime_seconds` | `outcome` | 2 (`confirmed`, `expired`) |
| All others | — | 1 |

No metric uses dynamic labels (item IDs, reservation IDs, customer IDs).
Total time-series count at full deployment: **≤ 40**.

---

## Observability Budget

Adding a new metric to this system requires staying within the following budget.
Any metric that would breach a limit must be discussed before merging.

| Constraint | Limit | Rationale |
|---|---|---|
| Total time-series | ≤ 40 | Keeps Prometheus memory predictable at low traffic volumes |
| Labels per metric | ≤ 3 | Beyond 3, cardinality explosion risk grows exponentially |
| Dynamic labels | **Forbidden** | Labels whose values come from runtime data (IDs, slugs, IP addresses) cause unbounded time-series growth |
| Cardinality per label | Bounded and known at deploy time | Must be enumerable before the metric ships — no "we'll see what values appear" |
| Histogram bucket sets | Fixed at definition time | Changing buckets mid-deployment creates discontinuous series; plan buckets for the full expected range upfront |

### How to evaluate a new metric

Before adding a metric, answer these questions:

1. **Is this a Counter, Gauge, or Histogram?** Never use a Gauge for something that only goes up (use Counter). Never use a Histogram with > 12 buckets without justification.
2. **Does it have labels?** List every possible label value. If you cannot enumerate them exhaustively, the label is dynamic — forbidden.
3. **What is the max time-series count?** Multiply cardinalities of all labels. Add this number to the current total (≤ 40). If it exceeds 40, discuss first.
4. **What alert will it enable?** A metric with no actionable alert is noise. Write the alert expression before shipping the metric.
5. **Is there an ADR or Runbook entry?** Add a card to this document before the PR merges.
