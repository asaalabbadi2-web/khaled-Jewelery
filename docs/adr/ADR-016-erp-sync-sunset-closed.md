# ADR-016 — ERP Sync: OrderCreated Consumer + ADR-013 Sunset Clause Renegotiation

**Status:** Accepted
**Date:** 2026-07-14
**Sprint:** 8 — ERP Sync

---

## Context

ADR-012 (*Inventory Strangler Fig*) documented a known dual source-of-truth:
the ERP held the inventory record and the Commerce API held the sales record,
with no automated bridge between them.

ADR-013 (*Sunset Clause*) established the expiry condition: the bridge must
exist before Gate A (production payment keys) is unlocked. ADR-013 §5 proposed
**Option A** as the terminal fix: a shared `InventoryService` — a cross-system
service that the POS would call directly before committing a sale, giving it
real-time visibility into active online reservations.

Sprint 8 does **not** build Option A. This ADR declares that substitution
explicitly and re-accepts the residual risk under new terms.

---

## Decision

### What Was Built (Option B — Event Sync)

Instead of a shared `InventoryService` (Option A), Sprint 8 implements
asynchronous event synchronisation:

1. **ERPSyncWorker** (Commerce API) polls `outbox_events WHERE event_type =
   'OrderCreated' AND erp_synced_at IS NULL`. For each event it POSTs to
   `POST /api/internal/online-orders` on the ERP Flask server, then marks
   `erp_synced_at = now`. Three independent cursors in one table
   (`published_at` / `notification_dispatched_at` / `erp_synced_at`).

2. **ERP Internal Endpoint** (`POST /api/internal/online-orders`, Flask) is
   machine-to-machine only, guarded by `X-Internal-Secret` (`secrets.compare_digest`).
   For each new order it finds the Item, creates an Invoice
   (`invoice_type='بيع'`, `status='paid'`), creates an InvoiceItem, and
   decrements `Item.stock` — all in one transaction. Idempotent:
   `commerce_order_id` unique constraint returns 200 `already_processed` on
   duplicates.

3. **RefundWorker** polls `payment_intents WHERE status = 'REFUND_PENDING'`,
   calls `RefundGateway.refund(intent)` (today: `LogRefundGateway` stub),
   then transitions to `REFUNDED` and emits `RefundConfirmed`.
   `RefundGateway` is a Protocol — real Moyasar adapter is a Gate A blocker
   (same principle as SEC-002 for shipping).

4. **ReconciliationWorker** (daily) compares Commerce PAID orders against ERP
   invoices via `GET /api/internal/order-reconcile/{order_id}`. For each
   discrepancy it:
   - Increments `reconciliation_gaps_total{kind=...}` (Prometheus counter).
   - Writes a row to `reconciliation_findings` (open until `resolved_at` set).
   - Logs at `ERROR` level.
   Alert rule: `reconciliation_gaps_total > 0` → open incident. By the
   standard in architecture-v1.md §4.6: a gap is either explained or it is
   an incident.

### What Was NOT Built

**Option A (shared `InventoryService`) was deliberately not built.** The POS
still has no real-time call path into online reservation state at the moment of
a showroom sale. This is a renegotiation of the ADR-013 Sunset Clause, not
a fulfilment of its original promise.

### Why Option B Over Option A

Option A requires a synchronous cross-system call from the POS (Flutter +
ERP backend) into the Commerce API on every sale attempt. That coupling
introduces latency on the POS critical path, and a transient Commerce API
outage would block showroom sales. Option B keeps the systems decoupled and
makes the bridge observable via metrics.

The trade-off accepted here: the ERP Sync path is asynchronous, which
means a residual race window exists.

---

## INV-4 Residual Risk Under Option B

**The question ADR-013 was built to answer:** *What prevents the POS from
selling an item that has an active online reservation?*

**The honest answer under Option B:** Nothing prevents it at the moment of
payment confirmation. The protection window is:

> `payment_confirmation` → `ERPSyncWorker consumes OrderCreated` → `ERP stock decremented`

During this window, the ERP `Item.stock` still reads as available. A POS
sale against the same item could succeed.

The window is bounded in normal operation by the `erp_sync_lag` SLO.
It is theoretically unbounded if ERPSyncWorker is down.

**INV-4 status: ENFORCED AT POS WITH BOUNDED FAIL-OPEN WINDOW.**

Gate B is now implemented as a **service-level check inside the ERP POS sale
route** (`backend/routes/invoices.py`), not a screen-level UI hint:

- The check runs **before any DB write** (E4.0 invariant: read → if blocked, return
  409 with zero writes; only then enter the write path).
- Commerce API call is synchronous with a 2 s timeout.
- **Fail-open** on timeout or unreachable: the sale is allowed to proceed + WARNING
  logged + `gate_b_fail_open_total` counter incremented (observable).
- Blocked response: `{"error": "item_reserved_online", "item_id": …, "reserved_until": …}` (409).

**Trade-off accepted (Sprint 9 E4):** Fail-open preserves showroom availability
at the cost of a race window during Commerce API downtime. This is the same
risk category as the original Option B race window, but now bounded to the
duration of Commerce API unavailability (which is measured and alerted on) rather
than the ERPSyncWorker lag. Compensation path is unchanged.

Compensation path: if a double-sale occurs during the fail-open window, the
online order enters `REFUND_PENDING` and `RefundWorker` triggers a refund.
The customer is compensated; the item is not shipped. This is a business
failure, not a system failure — it has a defined resolution path.

### erp_sync_lag SLO

| Metric | `erp_sync_lag_seconds` (Prometheus Histogram) |
|--------|-----------------------------------------------|
| Measured as | `now (at sync) − outbox_event.created_at` |
| SLO | P95 ≤ 30 seconds |
| Alert | P95 > 30s → incident: ERPSyncWorker is behind, INV-4 compensation window is growing |
| Defined in | `apps/commerce-api/src/yasargold_commerce/metrics.py` |
| Recorded in | `ERPSyncWorker._sync_event()` on each successful sync |

### Gate B — Service-Level Enforcement (E4, Sprint 9)

Gate B is **implemented** as `backend/services/commerce_availability.py` + injection
in `backend/routes/invoices.py`. It is no longer a future pre-condition.

**Transaction boundary:** The check happens before `commission_amount = 0.0`, the
earliest line that begins downstream processing. All Invoice and stock writes happen
later. The 409 path writes zero rows — proven by `test_b2_reserved_item_zero_writes`.

**Fail-open contract:** Commerce timeout ≤ 2 s → allowed + WARNING. Designed for
showroom uptime: the showroom must not freeze because the online service is slow.
The observable proxy is `gate_b_fail_open_total` (in-process counter until Prometheus
is wired in M2.x).

**Seam Ledger row 7** tracks this integration (pending → confirmed when E4 tests merge).

Gate B is the sole preventive mechanism on the showroom side. The pre-condition
for publishing showroom items online remains: Gate B must be active and the fail-open
window must be within the accepted risk tolerance.

### Gate B — Frontend Layer (Priority 2, Sprint 10)

Gate B is now **complete end-to-end**: the POS UI checks Commerce availability
before the operator can confirm a sale, providing early feedback without waiting
for the backend 409.

**Component:** `apps/web/src/components/pos/PosAvailabilityGate.tsx`

**Flow:**
```
Operator selects item
    ↓
PosAvailabilityGateConnected auto-fetches GET /api/v1/catalog/items/{id}/availability
    ↓
Commerce evaluates online reservation state (read-only, no writes)
    ↓
POS renders domain state (AVAILABLE / RESERVED / TIMEOUT / UNREACHABLE)
    ↓
canProceed=false → sale blocked at UI level (confirm button absent)
canProceed=true  → operator may confirm; backend Gate B is the defence-in-depth layer
```

**State machine:**

| State | canProceed | Operator action |
|-------|-----------|-----------------|
| `IDLE` | false | Must trigger check first |
| `CHECKING` | false | Check in flight |
| `AVAILABLE` | true | "تأكيد البيع" button enabled |
| `RESERVED` | false | Blocked; retry button only; shows reservedUntil |
| `TIMEOUT` | true (fail-open) | Warning shown; proceed allowed |
| `UNREACHABLE` | true (fail-open) | Warning shown; proceed allowed |

**Fail-open policy:** Matches backend — timeout / unreachable → proceed with warning.
Both layers implement the same policy; the UI fail-open is covered by F4/F5 tests.

**Proof tests:** `apps/web/src/test/pos-availability.test.ts` (F1–F8):
- F1 available item, F2/F3 reserved item, F4 timeout, F5 unreachable, F6 retry,
  F7 zero-writes gate (`posCheckCanProceed` exhaustive across all states),
  F8 UX messages (STATE_STORY_REGISTRY + 6 stories)

**No cached availability:** The connected component auto-re-checks when `itemId`
changes. Operators have a manual retry button in all non-idle states. The backend
Gate B remains the write-time guard regardless of frontend state.

**Operator retry:** Available in all states after the initial check (AVAILABLE,
RESERVED, TIMEOUT, UNREACHABLE). Re-check calls Commerce fresh — no local caching.

---

## H-series Hardening — Gate B Timing Contract

Four hardening items applied to the Gate B layers (Sprint 10 brief).

---

### H1 — TOCTOU Status: ENFORCED (T2.2 — 2026-07-23)

**Status change:** INV-4 moved from MITIGATED to **ENFORCED** by Sprint 11 Track 2.2.

**What changed:** `add_invoice()` in `backend/routes/invoices.py` now calls
`request_pos_claim(item_id)` — from `backend/services/commerce_availability.py` —
**before any `db.session` write** (replacing the old `check_item_online_reservation`
read). Commerce receives the claim request, locks the item inside its own transaction,
and either grants or denies atomically. The ERP writes the invoice only after the grant.

**Design inversion achieved:**
> POS was: **asks then writes** (read Commerce state, then commit ERP).
> POS is now: **requests then writes** (claim Commerce lock, then commit ERP).

This is "Reserve, not Add-to-Cart" applied to the showroom POS. The availability
decision AND the lock live inside Commerce's own transaction boundary — the only
architecture that is correct, because Commerce owns the reservation state.

**Three-step ERP flow (T2.2):**
1. `request_pos_claim(item_id)` — BEFORE any write. DENY → return 409, zero writes.
2. Invoice + journal entry write (ERP transaction).
3. On success: `_confirm_pos_claims_best_effort(claims)`. On failure: `finally` block
   calls `_release_pos_claims_best_effort(claims)` — item freed immediately.

**Fail-open preserved (H2):** Commerce API timeout → `PosClaimResult(fail_open=True)`
→ sale proceeds + WARNING. The same H2 ceiling/circuit-breaker that existed for the
old check remains in effect. The fail-open window reintroduces a brief TOCTOU risk,
identical to pre-T2.2. This is the documented H2 trade-off.

**INV-4 status: ENFORCED.**
- Commerce holds the row lock inside its transaction for the duration of the ERP write.
- V3.b: concurrent online reservation while a pos-claim is ACTIVE is rejected by
  Commerce with 409 `ITEM_POS_CLAIMED` (proved by `TestV3MutualExclusion` in
  `apps/commerce-api/tests/e2e/test_pos_claims.py`).
- The ~100 ms TOCTOU window that existed under MITIGATED is closed.

**Remaining work (N3):** The `get_fail_open_count()` compat-shim in
`backend/services/commerce_availability.py` was kept for backward compatibility with
two tests. Terminal action: migrate those tests to `get_timeout_count() +
get_unreachable_count()` directly, then delete the shim.

**Known Gap witness closed:** `TestHSeriesHardening::test_h1_toctou_window_exists`
was xfail-strict (the machine guarded the debt). With T2.2 landed, it became
`test_h1_toctou_closed_by_pos_claim_protocol` — a positive assertion proving
`request_pos_claim` is called for the item before the invoice write. The machine
did its job: stayed RED until the debt was paid, then cleared on landing.

#### Residual Window N4 — Confirm-Fail → Orphaned Claim

"INV-4 is ENFORCED" is true **at point-of-sale**. There is a narrower, bounded
residual failure mode introduced by the best-effort confirm call:

```
ERP sale commits
    ↓
_confirm_pos_claims_best_effort() called — Commerce is unreachable
    ↓
confirm call fails silently (best-effort never raises)
    ↓
pos_claim stays ACTIVE with expires_at in the past (zombie)
    ↓
item appears available online until TTL sweeps it or reconciliation catches it
```

**Exposure duration:** TTL (default 30 s) + reconciliation interval (daily) = **≤ 24 hours**.
During this window, the sold item may accept an online reservation. The customer
cannot complete payment (the item's ERP stock is 0), so the reservation expires,
but the item appears available in the catalogue.

**Catch mechanism (F1):** `ReconciliationWorker._check_orphaned_pos_claims()` runs
in the daily pass. It finds pos_claims where `status='ACTIVE' AND expires_at < now - 5 min`
(zombie claims), calls `GET /api/internal/item-sale/{item_id}?after={claimed_at}` on the
ERP to confirm a sale was committed, and if so writes an `ORPHANED_CLAIM` finding row
to `reconciliation_findings`. Alert rule: `reconciliation_gaps_total{kind="ORPHANED_CLAIM"} > 0`
→ open incident. Ops confirms the item is marked correctly in Commerce; no customer refund
needed (the reservation expires before payment).

**Why this does not downgrade ENFORCED:** The prior MITIGATED window was open-ended —
a concurrent reservation could succeed AND the customer could pay AND the item would
ship. Under ENFORCED the window is bounded to the TTL (items cannot be double-confirmed
because the pos_claim blocks a new online reservation while ACTIVE), and the failure
mode is detected and corrected within 24 hours. "ENFORCED" names the point-of-sale
guarantee; N4 names its bounded residual.

**Witness test (F1):** `TestStepCOrphanedClaimGap::test_zombie_claim_with_erp_sale_inserts_finding_row`
in `apps/commerce-api/tests/contract/reconciliation/test_reconciliation_gap_injection.py`.

**Remaining N4 terminal fix:** Replace best-effort confirm with an outbox event
(`ClaimConfirmRequested`) so it survives network transients via at-least-once delivery —
same pattern as `ERPSyncWorker`. Until then, N4 is a Known Gap entry.

---

### H2 — Fail-Open Ceiling: Circuit-Breaker Observable

**Both layers fail-open** when Commerce is unreachable → combined effect is zero
barriers during a Commerce outage. The fail-open ceiling makes this condition
**observable and pageable** without changing fail-open behaviour (a killswitch
requires explicit operator consent).

**Policy:**
- Sliding window: `GATE_B_WINDOW_SECONDS` (default 600 s / 10 min), configurable.
- Ceiling: `GATE_B_CEILING` (default 10 events in window), configurable.
- Action: when `events_in_window > FAIL_OPEN_CEILING`, emit **`CRITICAL`** log once
  per crossing (suppressed while tripped; resets when window drops below ceiling).
- CRITICAL message text: "FAIL-OPEN CEILING BREACHED — zero barriers against selling
  online-reserved items. ACTION REQUIRED: verify Commerce API health."
- Behaviour: showroom POS continues uninterrupted. The CRITICAL is the signal for
  the on-call operator to decide whether to manually halt the online sales channel.

**Alert rule (to be wired in M2.x monitoring):**
`gate_b_ceiling_breached > 0` → page on-call (P1).

**On-call response SLA:** P90 acknowledgement within **15 minutes** of the CRITICAL
alert firing. This is the decision window: the operator reviews Commerce API health
dashboards and decides whether to manually halt the online sales channel.

**Maximum exposure during the decision window:**

```
max_unverified_pieces = online_published_inventory × (sell_rate_per_day × 15 min / 1440 min)
```

With the current inventory ceiling policy (only **non-showroom items** published
online until Gate B is ENFORCED — see §Gate B — Service-Level Enforcement):
- `online_published_inventory = 0` today → `max_exposure = 0 pieces` while the
  ceiling policy holds.

When the policy relaxes (a controlled rollout begins):
- Assume an initial batch of N ≤ 10 items online, sell rate R ≤ 2 items/day.
- `max_exposure = 10 × (2 × 15/1440) ≈ 0.21` → **less than 1 piece at risk**
  during a 15-minute response window.
- This is a measurable, bounded number — not "accepted risk" but **measured risk**.

**Review trigger:** if `online_published_inventory` grows beyond 50 items or
`sell_rate_per_day` exceeds 5, re-derive this calculation and raise it in the
next security review. The formula above is the canonical reference.

**Tests:** `test_h2_ceiling_emits_critical_when_breached`,
`test_h2_below_ceiling_no_critical`, `test_h2_ceiling_suppresses_repeated_critical`.

---

### H3 — Distinct TIMEOUT vs UNREACHABLE Metrics

Both `TIMEOUT` (Commerce did not respond within 2 s) and `UNREACHABLE` (Commerce
connection failed) map to `canProceed=true` in the UX — correct fail-open behaviour.
Their **causes differ** and carry different signals:

| Event | Log key | Signal |
|-------|---------|--------|
| `requests.Timeout` | `gate_b_timeout_total` | Early degradation — Commerce is responding but slowly |
| Any other exception | `gate_b_unreachable_total` | Hard failure — Commerce is down or network is cut |

A rising `gate_b_timeout_total` without a matching rise in `gate_b_unreachable_total`
is an early degradation signal (Commerce under load) that can be acted on before
UNREACHABLE spikes. Merging them into one counter would mask this early warning.

**Backward compatibility:** `get_fail_open_count()` returns
`_timeout_count + _unreachable_count` (unchanged for existing callers).

**Compat shim ledger (N3):**

| Item | Value |
|------|-------|
| Function | `get_fail_open_count()` in `backend/services/commerce_availability.py` |
| Status | **Compat shim** — kept for existing test callers only; no production callers |
| Current callers | `TestCommerceAvailabilityService::test_fail_open_increments_counter` (line ~166) and `TestHSeriesHardening::test_h3_mixed_events_tracked_separately` (line ~478) in `backend/tests/test_pos_availability_check.py` |
| Deletion trigger | When both callers above are migrated to call `get_timeout_count()` and `get_unreachable_count()` (or their sum) directly — at which point `get_fail_open_count()` has zero callers and can be deleted without a deprecation period |
| Owner | Gate B maintainer — the next Sprint that touches `commerce_availability.py` must migrate these two test calls and delete the shim |

**Tests:** `test_h3_timeout_increments_timeout_counter`,
`test_h3_unreachable_increments_unreachable_counter`, `test_h3_mixed_events_tracked_separately`,
`test_h3_separate_log_keys`.

---

### H4 — Timeout Budget: 5 s (frontend) vs 2 s (backend)

Two different budgets for the same Gate B availability check — documented here and in code.

| Layer | File | Budget | Rationale |
|-------|------|--------|-----------|
| Frontend UI | `apps/web/src/components/pos/PosAvailabilityGate.tsx` | **5 s** | Not on the write path. The Flask DB session is not open. A longer wait increases the chance of a definitive answer before falling back to fail-open. Operator sees a spinner, not a locked DB. |
| Backend ERP | `backend/services/commerce_availability.py` | **2 s** | On the write path. Flask-SQLAlchemy autobegin means the DB session is active during the HTTP call. A 2 s timeout keeps session idle time bounded and prevents POS terminal freezes. |

**Decision:** keep distinct budgets. They are different stakes, different callers,
different constraints. The comment in each file cross-references this table.

---

## Security Boundary — SEC-003

`/api/internal/*` was not exposed before Sprint 8. It now receives
machine-to-machine calls from ERPSyncWorker and ReconciliationWorker.

**Trust boundary (declared explicitly):**

> The ERP internal API assumes the caller is on the same private network as
> the ERP Flask server. `X-Internal-Secret` (`secrets.compare_digest`) is the
> authentication layer within that network. Any network path from outside the
> private subnet to port 5000 on the ERP server must be blocked at the
> infrastructure level (firewall / security group). The secret-based guard is
> a defence-in-depth layer, not a substitute for network isolation.

This is documented in `backend/internal_routes.py` module docstring and in
`architecture-v1.md §4.6` as SEC-003 (status: Mitigated — guard is live,
terminal fix is mTLS when infrastructure is hardened).

The `ERP_INTERNAL_SECRET` env var must be set in production. If unset, the
endpoint returns 503 (deliberately unconfigured, not silently open).

---

## Domain Additions

| Addition | Purpose |
|----------|---------|
| `RefundGateway` Protocol | Same pattern as `ShippingGateway` — provider-agnostic refund call |
| `RefundConfirmed` domain event | Event-of-record for confirmed refunds; enables GL reversal downstream |
| `PaymentService.mark_refunded()` | Transitions `REFUND_PENDING → REFUNDED`, emits `RefundConfirmed` |
| `refunded_at` on `PaymentIntentRow` | Timestamp column for refund completion |
| `erp_synced_at` on `OutboxEventRow` | Third independent cursor on `outbox_events` |
| `commerce_order_id` on ERP `Invoice` | Idempotency key for at-least-once delivery |
| `ReconciliationFindingRow` ORM | Persistent record of open reconciliation gaps |

---

## ADR-013 Sunset Clause: Renegotiation Declared

ADR-013 required a bridge between Commerce and ERP before Gate A. That
requirement is satisfied — the bridge exists and is observable. But the
*mechanism* changed:

| ADR-013 Original | ADR-016 Actual | Delta |
|-----------------|----------------|-------|
| Option A: shared `InventoryService` (synchronous POS check) | Option B: asynchronous event sync (`ERPSyncWorker`) | **Renegotiation — not fulfilment** |
| INV-4: "terminal fix" | INV-4: "managed by compensation + measured sync" | Risk re-accepted under new terms |
| Gate B: UX improvement | Gate B: **sole preventive mechanism on showroom side** | **Elevated from optional to mandatory** |

**ADR-013 is closed.** The Sunset Clause has expired and its condition (an
automated bridge before Gate A) is met. The substitution of Option B for
Option A is a deliberate architectural choice, not an oversight, and its
residual risk is explicitly re-accepted here.

Gate A remains blocked only on:
1. `MoyasarRefundGateway` + staging E2E with real Moyasar sandbox credentials.
2. Real SMS notification adapter (Sprint 6 remnant).
3. Real carrier adapter (Sprint 7 remnant, SEC-002).
4. `reconciliation_gaps_total` alert wired up in the monitoring stack.

---

## Consequences

### Positive

**Dual source-of-truth bridged.** Every online sale now creates an ERP
invoice atomically (from the ERP's perspective). The ERP remains the GL
record; Commerce is the order status and customer comms record.

**Idempotent by design.** `commerce_order_id` unique constraint makes
at-least-once delivery from ERPSyncWorker safe. No double invoices.

**Reconciliation is an open incident, not a log line.** `reconciliation_findings`
rows stay open until explained. `reconciliation_gaps_total > 0` is
page-worthy.

**Refund loop closed (Gate A path).** `REFUND_PENDING` intents now have an
automated path to `REFUNDED`. `RefundConfirmed` event enables accounting
journal reversal downstream.

### Watch Out For

**`LogRefundGateway` in production** = no actual refunds. Gate A blocker.

**`erp_sync_lag` P95 > 30s** = INV-4 compensation window is growing.
This is the canary for ERPSyncWorker health.

**Gate B not closed** = listing showroom items online exposes INV-4.
Do not advance the item catalogue to showroom stock until Gate B is resolved.

---

## Related

- ADR-012 — Inventory Strangler Fig (dual source-of-truth documented)
- ADR-013 — Sunset Clause (this ADR closes and renegotiates it)
- ADR-014 — Notifications (same worker + outbox cursor pattern)
- ADR-015 — Clock Protocol (applied in RefundWorker)
- **ADR-023 M2.1** — the transitional state under Option B ends through Inventory extraction; M2.1 is the mechanism that closes INV-4 fully and retires the fail-open window of Gate B's service check
- §4.6 Known Gaps — INV-4, SEC-003 entries
- §10 Roadmap — Gate A/B status table
