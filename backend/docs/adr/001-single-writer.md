# ADR-001: Single Writer for Inventory (InventoryPostingService)

**Status:** Accepted  
**Date:** 2026-07-05  
**Deciders:** Architecture review

---

## Context

The system needs to track gold inventory weight across branches, categories, and karats. Multiple business documents create inventory movements: sales invoices, purchase invoices, customer scrap purchases, returns, count adjustments, and future documents (transfers, manufacturing, reclass).

Before this decision, each invoice type contained its own weight-update logic scattered across `routes.py`. Adding a new document type meant finding all the places where weight was affected and replicating the pattern — with no central enforcement of correctness.

## Decision

All writes to `InventoryLedger` and `InventoryBalance` are funneled through a single class: `InventoryPostingService`.

```
Any Business Document
        ↓
InventoryPostingService.post(document)   ← the only writer
        ↓
InventoryLedger (append)  +  InventoryBalance (update)
```

No other code path may write to these two tables directly.

`InventoryPostingService` dispatches to a private handler per document type:
- `_post_invoice(invoice)`
- `_post_adjustment(adjustment)`
- _(future)_ `_post_transfer(transfer)`

## Consequences

**Positive:**
- Every inventory movement, regardless of origin, produces the same Ledger + Balance structure.
- Adding a new document type requires only one new `_post_X()` handler — no hunting through the codebase.
- Idempotency, locking, and balance-update logic live in one place and are never duplicated.
- `BalanceInvariantChecker` can assert correctness globally because there is only one writer to audit.

**Negative / Trade-offs:**
- `InventoryPostingService` must be imported wherever a document is posted (invoices, adjustments, future transfers). This is an intentional coupling — the alternative (each document posting itself) is worse.
- The dispatcher `isinstance` check grows as new document types are added. This is acceptable; it is exhaustive and fails loudly (`TypeError`) for unknown types.

## Alternatives considered

- **Direct writes per service**: Each service (InvoiceService, AdjustmentService) writes to the Ledger itself. Rejected: duplicates locking/idempotency logic and creates multiple undocumented writers.
- **Event bus**: Documents emit events; a listener updates the Ledger. Rejected: adds async complexity and makes transaction atomicity harder to guarantee.
