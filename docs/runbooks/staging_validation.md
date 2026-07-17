# Staging Validation Runbook — Sprint 3.5

**Purpose**: Validate the Reservation + Outbox + Expiry stack under real
PostgreSQL and concurrency conditions before any production deployment.

**Prerequisite**: `alembic upgrade reservation_outbox_001` completed on Staging DB.

---

## Gate 1 — Schema

Verify the migration created everything correctly.

```sql
-- Tables exist
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('reservations', 'outbox_events');

-- Partial unique index exists (INV-6 Layer 2)
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'reservations'
  AND indexname = 'ix_reservations_active_item';
-- Expected: CREATE UNIQUE INDEX ix_reservations_active_item ON reservations (item_id)
--           WHERE (status = 'ACTIVE')

-- Outbox index exists
SELECT indexname FROM pg_indexes
WHERE tablename = 'outbox_events'
  AND indexname = 'ix_outbox_unpublished';

-- Columns and types
\d reservations
\d outbox_events
```

**Pass criteria**: Both tables exist, `ix_reservations_active_item` is UNIQUE
PARTIAL on `(item_id) WHERE status = 'ACTIVE'`, `ix_outbox_unpublished` exists.

---

## Gate 2 — Functional

Test each capability individually before adding concurrency.

### 2a. Infrastructure smoke test

```bash
curl -s https://staging.yasargold.com/health          # {"status": "ok"}
curl -s https://staging.yasargold.com/metrics | head  # # HELP reservation_success_total ...
curl -s https://staging.yasargold.com/api/v1/catalog/products | python3 -m json.tool
```

### 2b. Reservation flow

```bash
# 1. Pick a product slug from the catalog
SLUG=$(curl -s .../api/v1/catalog/products | python3 -c \
  "import sys,json; print(json.load(sys.stdin)['items'][0]['slug'])")

# 2. Create reservation
curl -s -X POST .../api/v1/reservations \
  -H "Content-Type: application/json" \
  -d "{\"item_slug\": \"$SLUG\"}" | python3 -m json.tool
# Expected HTTP 201, body contains reservation_id (res_...) and quote_id (qt_...)
```

Verify in DB:

```sql
SELECT id, quote_id, item_id, status, reserved_at, valid_until
FROM reservations
WHERE status = 'ACTIVE'
ORDER BY reserved_at DESC
LIMIT 5;

SELECT id, event_type, published_at
FROM outbox_events
ORDER BY created_at DESC
LIMIT 5;
-- published_at should be NULL (Worker hasn't run yet)
```

### 2c. Outbox Worker

```bash
# Run one tick manually
python -m yasargold_commerce.workers.outbox_worker --once
# or: python -c "
# from yasargold_commerce.workers.outbox_worker import OutboxWorker
# from yasargold_commerce.db import SessionLocal
# worker = OutboxWorker(SessionLocal, lambda t, p: print(t, p))
# worker.run_once()
# "
```

Verify:

```sql
SELECT published_at FROM outbox_events ORDER BY created_at DESC LIMIT 5;
-- published_at should now be NOT NULL
```

### 2d. Expiry Worker

Create a reservation, wait for it to expire (or manually set `valid_until` to
the past), then run the Expiry Worker:

```sql
-- Force-expire for testing (Staging only)
UPDATE reservations SET valid_until = NOW() - INTERVAL '1 second'
WHERE id = 'res_...' AND status = 'ACTIVE';
```

```bash
python -m yasargold_commerce.workers.expiry_worker --once
```

Verify:

```sql
SELECT status FROM reservations WHERE id = 'res_...';
-- Expected: EXPIRED

SELECT event_type FROM outbox_events WHERE payload LIKE '%res_...%';
-- Expected: yasargold_domain.reservation.events.ReservationExpired
```

**Pass criteria**: All 4 sub-tests produce expected DB state.

---

## Gate 3 — Concurrency

This gate proves INV-6 (double-reservation prevention) under load.

```bash
# 50 concurrent requests on the same item
python scripts/concurrency_test.py \
  --url https://staging.yasargold.com \
  --slug $SLUG \
  --concurrency 50

# Expected output:
# Results: 1 × 201 Created, 49 × 409 Conflict
# Duplicate reservations: 0
# Test PASSED
```

If 50 passes:

```bash
# Escalate to 100
python scripts/concurrency_test.py \
  --url https://staging.yasargold.com \
  --slug $SLUG \
  --concurrency 100
```

**Pass criteria**: Exactly 1 × 201, remainder × 409, zero duplicates in the DB.

```sql
-- Confirm no duplicates in DB
SELECT item_id, COUNT(*) as active_count
FROM reservations
WHERE status = 'ACTIVE'
GROUP BY item_id
HAVING COUNT(*) > 1;
-- Expected: 0 rows
```

---

## Gate 4 — Observability

Run the functional and concurrency tests, then verify every metric moved.

```bash
curl -s https://staging.yasargold.com/metrics | grep -E \
  "reservation_success_total|reservation_conflict_total|reservation_lock_duration|quote_age_seconds"
```

Expected after 50-concurrent test:

```
reservation_success_total 1.0
reservation_conflict_total 49.0       # or higher if re-ran
reservation_lock_duration_seconds_count N
quote_age_seconds_count 1.0
```

After running Expiry Worker:

```
reservation_expired_total N
reservation_lifetime_seconds_bucket{outcome="expired",...} N
expiry_worker_batch_size_reservations_count N
```

After running Outbox Worker:

```
outbox_batch_size_events_count N
outbox_publish_duration_seconds_count N
```

### OUTBOX_EVENTS_PENDING — expected behaviour

`outbox_events_pending` is an **operational gauge** (best-effort snapshot),
not a transactional counter.

**How it is updated**: each Outbox Worker tick runs a `COUNT(*)` query inside
its own transaction and calls `Gauge.set(count)` before processing the batch,
then `Gauge.dec(len(batch))` after commit. With multiple concurrent Workers,
each sets the gauge independently, so values from different Workers can
interleave on the Prometheus scrape side.

**What to expect**:
- Value will fluctuate during concurrent Worker runs — this is normal.
- Value may briefly appear higher than reality (stale snapshot from a Worker
  that ran before another Worker committed its batch).
- Value will not go negative (each Worker calls `set()` with the actual COUNT
  then `dec()` — the floor is 0 from Prometheus's perspective, not from the
  application's).

**The authoritative source of truth** when investigating a backlog:

```sql
SELECT COUNT(*) FROM outbox_events WHERE published_at IS NULL;
```

Use the Gauge for **trend detection** (backlog growing over time) and for
**alerts** (see metrics reference). Use the SQL query for **incident
investigation**.

---

## Load Test (optional, Gate 5)

After gates 1–4 pass, run a 10–15 minute sustained load to check for
connection leaks:

```bash
# Sustained load — adjust rate to realistic traffic estimate
hey -n 5000 -c 10 -m POST \
  -H "Content-Type: application/json" \
  -d '{"item_slug":"'$SLUG'"}' \
  https://staging.yasargold.com/api/v1/reservations
```

Monitor:

```sql
-- DB connection pool
SELECT count(*), state FROM pg_stat_activity
WHERE datname = 'yasargold_staging'
GROUP BY state;
-- 'idle' count should be stable, not growing
```

**Pass criteria**: Connection count stable across the 15-minute window.

---

## Sign-off

| Gate | Tested by | Result | Date |
|---|---|---|---|
| Gate 1 — Schema | | | |
| Gate 2 — Functional | | | |
| Gate 3 — Concurrency (50) | | | |
| Gate 3 — Concurrency (100) | | | |
| Gate 4 — Observability | | | |
| Gate 5 — Load (optional) | | | |

All gates must show PASS before promoting to production or beginning Sprint 4.
