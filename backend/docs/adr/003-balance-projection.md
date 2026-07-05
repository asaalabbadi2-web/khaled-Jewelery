# ADR-003: InventoryBalance as a Synchronous Projection

**Status:** Accepted  
**Date:** 2026-07-05  
**Deciders:** Architecture review

---

## Context

`InventoryLedger` is the source of truth (ADR-002), but computing `SUM(weight_delta)` per bucket on every balance read is expensive under load. A read-optimised cache is needed.

Two approaches were considered: asynchronous projection (eventual consistency) and synchronous projection (strong consistency).

## Decision

`InventoryBalance` is a **synchronous projection** — it is updated in the **same database transaction** as the Ledger write:

```python
# Inside InventoryPostingService._post_invoice():
db.session.add(ledger_row)
db.session.flush()          # ledger_row.id is now known
_apply_to_balance(ledger_row)  # updates InventoryBalance in same txn
```

`_apply_to_balance()` uses `SELECT FOR UPDATE` on the balance row to prevent race conditions under concurrent writes on PostgreSQL.

`InventoryBalance` stores:
- `balance`: current cached `SUM(weight_delta)` for the bucket
- `snapshot_max_ledger_id`: the last `InventoryLedger.id` applied

If `InventoryBalance` ever diverges from the Ledger (e.g. due to a bug), it can be rebuilt by deleting all balance rows and replaying the Ledger — the Ledger is never affected.

## Consequences

**Positive:**
- Balance reads are O(1) — no aggregation needed.
- No eventual-consistency lag: the projected balance is accurate at the moment of commit.
- `snapshot_max_ledger_id` enables the reconciliation report to detect partial replays.

**Negative / Trade-offs:**
- Every post adds one more DB operation (SELECT + UPDATE/INSERT on `inventory_balance`). This is acceptable; gold ERP transaction volumes are low (tens/hundreds per day, not millions).
- `SELECT FOR UPDATE` adds a row lock per bucket per transaction. Under concurrent writes to the same bucket, transactions serialise. This is correct behaviour for a financial system.

## Rebuild procedure

```sql
DELETE FROM inventory_balance;
-- Then run InventoryBalanceRebuildService.rebuild_all() (Phase 5)
-- which replays all Ledger rows in id order
```

`BalanceInvariantChecker.assert_clean()` verifies the projection is correct at any time.

## Alternatives considered

- **Async projection (event-driven)**: Write to Ledger immediately, update Balance later via a background worker. Rejected: introduces a consistency window where Balance lags Ledger, which is unacceptable for a financial system used for real-time decisions.
- **No projection, always compute from Ledger**: Simpler, but O(n) per balance read. Rejected for production; acceptable only in tests.
