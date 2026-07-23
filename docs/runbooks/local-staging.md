# Local Staging Environment

**Owner:** Engineering  
**Authority:** `docker-compose.local.yml`, `Makefile`, `seed/`  
**See also:** ADR-015 §Clock Discipline, ADR-016 §Gate B, ADR-023 §Seam Rule

---

## Why local-full beats live-ERP

Running against a local, fully-seeded staging environment is a hard requirement for
correctness testing — not a convenience.  Live ERP cannot be used because:

| Problem | With live ERP | With local-full |
|---------|--------------|-----------------|
| Synthetic reservations | Cannot create test reservations without polluting live data | Seed any state freely |
| Confirm-failure simulation | Would trigger real ERP write failures | Inject any error via env vars |
| Claim-race testing (INV-4) | Concurrent POS claims → corrupts real inventory | Race safely against seed stock |
| Reconciliation gap injection | Diverging the live books is irreversible | Reset with `make reset` in 30 s |
| Gate B fail-open window | Would page on-call if commerce-api goes down | Toggle commerce container freely |
| Clock drift tests | Cannot stop the production NTP clock | Inject any `now` via worker env |
| Two-DB TOCTOU visibility | Shared DB hides the claim-race and N+4 boundary | Two separate DBs make it explicit |

**Summary:** anything that changes shared production state (inventory, ledger, reservations)
cannot be safely tested against live data.  The claim-race and reconciliation tests in
particular require complete control of both sides of the seam.

---

## Schema Management

**Commerce API** uses Alembic (`apps/commerce-api/alembic/`).  Migrations run as an
explicit deploy step — the `commerce-migrate` service in Compose, or `make migrate`
locally.  The API lifespan does NOT call `create_all()` or any auto-migrate.  This
mirrors the production deploy flow where Alembic runs in CI before the API container
starts.

**ERP** calls `db.create_all()` on startup (existing pattern, unchanged).

New Commerce API schema changes → write an Alembic migration → commit it → `make migrate`.

---

## Hard Rules

1. **No production connection.**  This environment MUST NOT connect to the production ERP
   or production PostgreSQL.  Not via Tailscale, not via direct IP.
   If you need to test against a remote ERP, it must be a dedicated **staging ERP** on a
   separate host — never production.

2. **Two separate databases.**  `postgres-erp` and `postgres-commerce` are different
   containers with different credentials and different schemas.  The shared-DB production
   architecture is an acknowledged gap (see Known Gaps table); local staging makes that
   boundary explicit so integration bugs are visible here, not in production.

3. **ERP has no host port.**  The `erp` container exposes port 8001 only on the internal
   `yasargold` Docker network.  No `ports:` block — constitution §1.3.

4. **Sandbox gateways only.**  `COMMERCE_ENV=development` forces log-only adapters for
   Moyasar, Twilio, and Aramex.  No real payment, SMS, or shipping call is ever made.

---

## Quick Start

```bash
# First time (or after code changes):
make reset   # tears down volumes, rebuilds images, seeds data, creates admin

# Subsequent starts (preserves data):
make up

# Check everything works:
make smoke

# Follow logs:
make logs

# Run the Next.js storefront on the host (points to localhost:8000):
make web

# Tear down:
make down
```

---

## Services

| Service | Internal address | Host port | Notes |
|---------|-----------------|-----------|-------|
| `postgres-erp` | `postgres-erp:5432` | 5433 | ERP PostgreSQL (inspection only) |
| `postgres-commerce` | `postgres-commerce:5432` | 5434 | Commerce PostgreSQL (inspection only) |
| `redis` | `redis:6379` | — | Rate limiting & queue |
| `erp` | `erp:8001` | **none** | ERP Flask/gunicorn — internal only |
| `commerce` | `commerce:8000` | 8000 | Commerce FastAPI |
| `workers` | — | — | All background workers |

---

## Seed Data

Seed files live in `seed/`.  They are idempotent (`ON CONFLICT DO NOTHING`).

**Commerce DB** (`seed/commerce_seed.sql`): categories 1–3, items 101/102/201/301/302,
gold_price row 1.

**ERP DB** (`seed/erp_seed.sql`): settings row 1, minimum chart of accounts, matching
categories and items.  Admin user is created separately by `make seed-admin` (Python,
because bcrypt hashes cannot be generated portably in SQL).

**Critical invariant:** item IDs in both seed files must always match.  The two DBs
represent the same physical items.  A mismatch hides TOCTOU and claim-race bugs.

---

## End-to-End Flow (reservation → checkout → pos-claim)

```bash
# 1. Reserve item 101
RESERVATION=$(curl -sf -X POST http://localhost:8000/api/v1/items/101/reserve \
  -H "Content-Type: application/json" \
  -d '{"customer_phone": "+966500000001", "ttl_seconds": 300}')
echo $RESERVATION

RESERVATION_ID=$(echo $RESERVATION | python3 -c "import sys,json; print(json.load(sys.stdin)['reservation_id'])")

# 2. Create payment intent
INTENT=$(curl -sf -X POST http://localhost:8000/api/v1/payments \
  -H "Content-Type: application/json" \
  -d "{\"reservation_id\": \"$RESERVATION_ID\", \"amount\": 85500}")
echo $INTENT

# 3. (In production: Moyasar webhook confirms payment)
# In staging: use the test webhook endpoint or advance directly to checkout

# 4. POS claim (ERP → Commerce, machine-to-machine)
curl -sf -X POST http://localhost:8000/api/v1/items/101/pos-claim \
  -H "X-POS-Secret: local-pos-secret-dev" \
  -H "Content-Type: application/json" \
  -d '{"pos_terminal_id": "T-LOCAL-01"}'
```

---

## Workers Note

In local staging, all Commerce background workers run in daemon threads inside the
`workers` container (`run_workers.py`).  This is a local convenience only — two
important differences from production:

1. **`ReconciliationWorker`** runs in a polling loop (it only has `run_once()`, not
   `run_forever()`).  In production it MUST run in a separate container with an
   external scheduler (cron / Celery beat / k8s CronJob) — not as a thread inside
   the API process.  Daemon threads die with the process; if the workers container
   restarts, reconciliation silently stops.  See debt register row LOCAL-SCHEDULER-001.

2. All workers share one process restart policy.  In production each worker should
   have its own container and restart boundary.

---

## Clock Discipline in Staging

Container NTP synchronises system clocks for logs and metrics only.  All
reservation-expiry, payment-intent voiding, and shipment void-window decisions use
an injected `now` parameter sourced from the database clock at the transaction boundary.

See **ADR-015 §Clock Discipline** for the governing rule.  The worker containers are
configured to use the same DB clock via the injected boundary pattern — NTP drift does
not affect business decisions.

---

## Resetting

```bash
make reset   # wipes all volumes, rebuilds images, re-seeds, recreates admin user
```

This is safe to run at any time.  It does not touch production.
