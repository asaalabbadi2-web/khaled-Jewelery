# ADR-012: ERP Transitions from Source of Truth to Downstream Consumer

**Status:** Accepted  
**Date:** 2026-07-13  

---

## Rule

Commerce is the system of record for all transactional state.  
ERP receives `OrderCreated` events and produces GL entries.  
ERP never initiates a write to Commerce.

---

## Context

### The original design (v0)

The platform was conceived with a single shared domain: ERP and Commerce would call the same domain services. The ERP was the primary system; Commerce was a new channel built on top of it.

### What actually happened

Five sprints of building Commerce from the ground up produced a domain model (Reservation, PaymentIntent, Order) that is richer, more testable, and more correct than the ERP equivalent. The ERP monolith, by contrast, carries a decade of business logic embedded in Flask routes with no domain separation.

Forcing Commerce to call ERP services would have meant:

- Importing Flask/SQLAlchemy models into domain packages (violates ADR-006)
- Accepting ERP's coupling style in new capabilities
- Slowing every Commerce transaction by the ERP's synchronous model

### The strangler fig

The decision is to apply the strangler-fig pattern:

1. Commerce owns transactional state *for new transactions*
2. ERP continues to own historical records
3. At Sprint 8, `OrderCreated` events flow from Commerce to ERP via the Outbox

---

## Decision

**Commerce → Outbox → ERP** (not ERP → Commerce)

```
Commerce creates Order
     │
     ▼
outbox_events (same transaction)
     │
     ▼  [Sprint 8 consumer]
ERP creates Invoice + GL entry
```

---

## Dual Source of Truth — Transition Period

Until Sprint 8 is complete, there is a **deliberate dual source of truth**:

| Entity | Authoritative system |
|--------|---------------------|
| Order | Commerce PostgreSQL |
| Invoice | ERP database |
| GL entries | ERP database |
| Item availability | ERP (POS) + Commerce (online) — see ADR-013 |

The lag between `OrderCreated` and ERP invoice creation is bounded by the Outbox consumer's polling interval (target: < 30 seconds).

### Reconciliation contract

A daily reconciliation job compares:
- `orders WHERE status = CONFIRMED AND created_at > T`
- `invoices WHERE source = 'commerce_order' AND created_at > T`

Any `order_id` present in Commerce but absent in ERP triggers an alert.  
The repair path: re-publish `OrderCreated` from the Outbox (at-least-once delivery).

---

## Consequences

**Positive:**
- Commerce domain stays clean — no ERP imports
- ERP migration can happen gradually, table by table
- Future ERP replacement does not require Commerce changes

**Negative:**
- Temporary dual source of truth requires reconciliation monitoring
- ERP staff see orders with a lag (< 30 seconds in steady state)
- Any ERP outage does not block Commerce transactions, but creates reconciliation debt

---

## Answers to the Three Required Questions

1. **Why did Commerce become the source of truth?**  
   Five sprints produced a richer, more correct domain model in Commerce.  
   The ERP monolith has business logic in routes with no domain boundary.  
   Inverting the dependency removes the weaker system from the critical path.

2. **Why did ERP become a consumer?**  
   The strangler-fig pattern is the lowest-risk path for a live system.  
   ERP continues functioning without changes; new behaviour is added as event consumers.

3. **How is reconciliation handled when events fail?**  
   Outbox provides at-least-once delivery. The daily reconciliation job catches any gaps.  
   The Outbox `published_at` column distinguishes delivered from pending events.
