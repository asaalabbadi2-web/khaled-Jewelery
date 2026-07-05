# ADR-005: Inventory Adjustment as a Difference Document

**Status:** Accepted  
**Date:** 2026-07-05  
**Deciders:** Architecture review

---

## Context

After a physical count session is approved, the system must correct the inventory balance for any buckets where the physical count differed from the expected balance. Additionally, standalone corrections are needed for write-offs, manufacturing losses, and other events.

Two design options:
1. **Direct balance update**: `approve_session()` modifies `InventoryBalance` directly based on variance.
2. **Difference Document**: `approve_session()` creates an `InventoryAdjustment` document that flows through `InventoryPostingService` like any other document.

## Decision

`InventoryAdjustment` is a **Difference Document** — it stores the variance (`variance_weight = counted - expected`) and is always posted through `InventoryPostingService`:

```
InventoryCountSession (approved)
        ↓
InventoryAdjustmentService.create_from_session()
        ↓
InventoryAdjustment (Difference Document)
        │  variance_weight per bucket
        ↓
InventoryPostingService.post(adjustment)   ← Single Writer (ADR-001)
        ↓
InventoryLedger (movement_type='adjustment')
        ↓
InventoryBalance (updated atomically)
        ↓
InventoryAccountingService.post_adjustment_to_gl()  ← GL layer (Phase 5)
```

`InventoryAdjustmentService` never writes to `InventoryLedger` or `InventoryBalance` directly.

**GL separation:**  
`InventoryAdjustmentService` does not know about Chart of Accounts.  
GL creation is delegated to `InventoryAccountingService`, a separate class whose only job is mapping inventory movements to journal entries. This allows future document types (transfers, manufacturing) to reuse the same GL layer without inheriting inventory logic.

## Consequences

**Positive:**
- ADR-001 (Single Writer) is preserved: every inventory correction, regardless of origin, flows through `InventoryPostingService`.
- The Ledger audit trail includes adjustment entries — auditors can see exactly when and why each correction was made (`posted_at`, `posted_by`, `notes`).
- Future document types (transfer, manufacturing, reclass) follow the same pattern: create a document, call `InventoryPostingService.post()`, done.
- GL logic is isolated in `InventoryAccountingService` — changes to the Chart of Accounts do not require modifying adjustment or count logic.

**Negative / Trade-offs:**
- An extra `InventoryAdjustment` row is created even for small single-bucket corrections. This is intentional — every correction should be traceable to a document.
- `approve_session()` now returns `(session, adjustment)` instead of just `session`. Callers must handle the tuple. This is documented and tested.

## Invariant after approval

After `approve_session()` completes:

```
InventoryBalance.balance
    == SUM(InventoryLedger.weight_delta)
    == physical count

BalanceInvariantChecker.assert_clean()  # must pass
```

This is verified by `test_invariant_holds_after_approve`.

## Related

- ADR-001: Single Writer — why adjustment goes through InventoryPostingService
- ADR-002: Append-only Ledger — adjustment creates new rows, never modifies old ones
- ADR-004: Count Snapshot — why expected_weight is frozen at session open
