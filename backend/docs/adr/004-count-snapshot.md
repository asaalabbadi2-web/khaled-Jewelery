# ADR-004: Count Session Snapshot via Ledger ID (not Timestamp)

**Status:** Accepted  
**Date:** 2026-07-05  
**Deciders:** Architecture review

---

## Context

When a physical inventory count session opens, the system must freeze the "expected" balance — the balance as of the moment the counting began. Any inventory movements that occur _during_ the count (invoices posted while staff are counting) should not retroactively change what was expected.

Two approaches to define "the cutoff point":
1. Use `opened_at` timestamp and filter `InventoryLedger WHERE posted_at <= opened_at`
2. Use `MAX(InventoryLedger.id)` at open time and filter `WHERE id <= snapshot_ledger_id`

## Decision

The snapshot cutoff is `snapshot_ledger_id = MAX(InventoryLedger.id)` captured once at session open:

```python
max_id = db.session.query(func.max(InventoryLedger.id)).scalar() or 0
session.snapshot_ledger_id = max_id
```

Expected balance for a count line = `SUM(weight_delta) WHERE id <= snapshot_ledger_id AND bucket = (branch, category, karat)`.

In practice, `InventoryCountService.populate_lines()` reads from `InventoryBalance` (which reflects all entries up to that point) — the snapshot_ledger_id is stored for auditability and future replay.

`InventoryCountLine.expected_ledger_id` stores the `InventoryBalance.snapshot_max_ledger_id` at populate time, answering "exactly which Ledger entry made the balance 523.42g?"

## Why Ledger ID, not Timestamp

| Factor | Timestamp | Ledger ID |
|---|---|---|
| Ordering guarantee | Wall clock (can have ties, skew) | Monotonic integer — strict order |
| Edge cases | Two entries with same second | None — each entry has a unique ID |
| Replay correctness | Requires precise timestamp comparison | Exact: `WHERE id <= N` |
| Traceability | Hard to answer "which entry last?" | `expected_ledger_id` points directly |

## Consequences

**Positive:**
- No edge cases around concurrent transactions with the same timestamp.
- `expected_ledger_id` on `InventoryCountLine` makes the expected balance fully explainable months later.
- Future replay / reconciliation can reconstruct the balance as of any snapshot point.

**Negative / Trade-offs:**
- `snapshot_ledger_id` is only meaningful while the Ledger row with that ID exists. If rows are ever archived (ADR-002 archival plan), the snapshot ID must be preserved or the corresponding balance snapshot must be materialised.

## Related

- ADR-002: InventoryLedger is append-only — IDs are stable and never reused.
- ADR-003: InventoryBalance.snapshot_max_ledger_id tracks the same concept at the projection level.
