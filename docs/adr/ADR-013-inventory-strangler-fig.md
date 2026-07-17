# ADR-013: Inventory — Strangler Fig (Option B) with Mandatory Sunset

**Status:** Accepted — Transitional  
**Date:** 2026-07-13  
**Sunset:** This ADR is invalid after Sprint 8 delivery. See §Sunset Clause.

---

## Rule

During the transition period, POS (ERP) remains the authoritative writer for item availability.  
Commerce enforces availability through two read-time checks (not a write lock).  
The terminal state is Option A: a shared `InventoryService` called by all channels.

---

## Context

### The gap (INV-4)

`ReservationService` (INV-6) prevents two concurrent *online* reservations for the same item.  
It does not prevent a POS sale via ERP while an online reservation is ACTIVE.

The ERP invoice creation route (`routes/invoices.py`) has no check against the  
`reservations` table. This is a confirmed production gap as of 2026-07-13.

### Why not Option A immediately (shared InventoryService)?

Option A requires modifying the ERP POS invoice creation path — the most heavily tested  
and business-critical route in the system. Doing this under "pre-freeze" pressure:

- Introduces risk to the production POS before any online sales volume exists
- Requires the `REFUNDED` state to exist first (compensation path for race conditions)
- Is the correct target but should be Sprint 8 work, not pre-v1.0 work

### The race window analysis

With two check points (see §Decision), the gap window is:

| Scenario | Window duration |
|----------|----------------|
| No checks | Full reservation lifetime (15 min) |
| Single checkout check only | Payment processing time (< 2 min) |
| **Double check (this ADR)** | **Time between availability check and payment capture (seconds)** |

The residual risk is a POS sale in the seconds between the `Checkout` availability  
check and the Moyasar payment capture. This risk is accepted for the transition period.

---

## Decision

### Three mandatory conditions for Option B to be production-acceptable:

**Condition 1 — Double availability check:**

```
POST /api/v1/reservations
  └── Check: is item AVAILABLE in ERP? (query items table)
      └── If not: 409 ITEM_NOT_AVAILABLE

POST /api/v1/webhooks/payment (checkout phase)
  └── Check: is item still not sold in ERP?
      └── If sold: → REFUND_PENDING path (not a crash)
```

**Condition 2 — POS visibility endpoint:**

`GET /api/v1/items/{item_id}/availability`

Returns the item's current reservation status so POS screens can display:  
`"محجوزة أونلاين حتى 10:12"` before a sale is attempted.

This is a **read-only** endpoint. It does not modify ERP and does not call any domain service write path.

**Condition 3 — Compensation path defined before activation:**

`REFUNDED` state in `PaymentIntent` must exist before any real monetary volume.  
The flow for the residual race condition:

```
POS sells item → ERP invoice created
     ↓
Webhook arrives → PaymentService.confirm() → PAID
     ↓
checkout_uow: item already sold → CheckoutService raises ItemNoLongerAvailableError
     ↓
HTTP layer: intent.mark_refund_pending() → commit
     ↓
RefundWorker: calls gateway.refund() → intent.mark_refunded() → commit
     ↓
Customer receives: automatic refund + apology notification [Sprint 6]
```

---

## Sunset Clause

**This ADR expires when Sprint 8 delivers a shared `InventoryService`.**

The terminal architecture (Option A):

```
packages/domain/inventory/
  service.py     ← reserve(item_id) / release(item_id) / confirm_sale(item_id)
  repository.py  ← Protocol
  events.py      ← ItemReserved, ItemSold, ItemReleased

ERP POS:
  invoice creation → InventoryService.confirm_sale(item_id)

Commerce:
  reservation → InventoryService.reserve(item_id)
  checkout    → InventoryService.confirm_sale(item_id)
```

At that point, INV-4 becomes a hard guarantee, not a probabilistic one.

**Any extension of Option B beyond Sprint 8 requires a new ADR.**  
Without this constraint, transitional solutions become permanent by inertia.

---

## Consequences

**Accepted:**
- Residual INV-4 window of seconds during transition
- POS staff must be trained to check the visibility endpoint before selling reserved items

**Required before activation:**
- `REFUNDED` + `REFUND_PENDING` states implemented in `PaymentIntent` (INV-10)
- `GET /api/v1/items/{id}/availability` endpoint deployed

**Not accepted:**
- Leaving INV-4 undocumented
- Extending Option B beyond Sprint 8 without explicit ADR
