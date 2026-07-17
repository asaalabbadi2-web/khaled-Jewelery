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

**INV-4 status: MANAGED BY COMPENSATION + MEASURED SYNC — NOT CLOSED.**

Compensation path (unchanged from ADR-013): if a double-sale occurs, the
online order enters `REFUND_PENDING` and `RefundWorker` triggers a refund.
The customer is compensated; the item is not shipped. This is a business
failure, not a system failure — it has a defined resolution path. The goal
of the sync SLO is to make the window small enough that this path is never
needed in practice.

### erp_sync_lag SLO

| Metric | `erp_sync_lag_seconds` (Prometheus Histogram) |
|--------|-----------------------------------------------|
| Measured as | `now (at sync) − outbox_event.created_at` |
| SLO | P95 ≤ 30 seconds |
| Alert | P95 > 30s → incident: ERPSyncWorker is behind, INV-4 compensation window is growing |
| Defined in | `apps/commerce-api/src/yasargold_commerce/metrics.py` |
| Recorded in | `ERPSyncWorker._sync_event()` on each successful sync |

### Gate B is Now the Sole Preventive Mechanism on the Showroom Side

Under Option A, the POS would have made a real-time check into online
reservation state before each sale — a hard block. Under Option B, no such
block exists. Gate B (POS UI consumes `GET /api/v1/items/{id}/availability`)
is no longer an optional UX improvement — it is **the only mechanism that
gives POS staff visibility into active online reservations before committing
a showroom sale**.

Gate B is therefore a mandatory pre-condition for listing showroom-displayed
items online. Before Gate B: only publish items *not physically present in
the showroom* — INV-4 exposure is zero by definition. After Gate B: the POS
visibility check is the human backstop.

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
- §4.6 Known Gaps — INV-4, SEC-003 entries
- §10 Roadmap — Gate A/B status table
