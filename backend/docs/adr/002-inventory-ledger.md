# ADR-002: Append-Only Event Log (InventoryLedger)

**Status:** Accepted  
**Date:** 2026-07-05  
**Deciders:** Architecture review

---

## Context

Gold inventory systems require a complete, auditable history of every weight movement. A mutable balance table (update-in-place) loses this history and makes it impossible to answer questions like "what was the inventory level at 14:32 on date X?" or "which document caused this discrepancy?"

## Decision

`InventoryLedger` is an **append-only event log**. Each row represents one inventory movement from one source line:

```
id | source_type | source_id | source_line_id | movement_type
   | branch_id  | category_id | karat | weight_delta
   | posted_at  | posted_by  | notes
```

**Rules:**
1. Rows are never updated or deleted — only inserted.
2. `weight_delta` is signed: positive = stock IN, negative = stock OUT.
3. Reversals are new rows with `movement_type = '<original>_reversal'` and `weight_delta = -original`, not modifications.
4. Current balance for a bucket = `SUM(weight_delta)` filtered by `(branch_id, category_id, karat)`.

**Idempotency** is enforced at two levels:
- Service level: check for existing row before inserting.
- Database level: `UNIQUE(source_type, source_id, source_line_id, movement_type)` constraint.

## Consequences

**Positive:**
- Complete audit trail — every gram movement is traceable to its source document and line.
- `BalanceInvariantChecker` can recompute the ground truth at any time from the Ledger alone.
- Snapshot isolation: count sessions can freeze a `snapshot_ledger_id` and compute expected balance at that exact point in history.
- Debugging: any balance discrepancy can be traced by replaying Ledger rows.

**Negative / Trade-offs:**
- The Ledger grows indefinitely. Archival strategy will be needed after ~5 years of operation (low priority; gold ERP data volumes are modest).
- Balance queries require `SUM()` over potentially many rows if not using the Balance projection. This is why `InventoryBalance` exists as a cache (see ADR-003).

## Alternatives considered

- **Mutable balance table only**: Update a single row per bucket on every transaction. Rejected: no history, impossible to audit, hard to debug drift.
- **Soft-delete / update-with-version**: Mark rows as cancelled instead of appending reversals. Rejected: complicates queries and breaks `SUM()` semantics.
