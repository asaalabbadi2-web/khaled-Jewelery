# ADR-006: Inventory, Accounting, and SafeBox as Independent Bounded Contexts

**Status:** Accepted  
**Date:** 2026-07-05  
**Deciders:** Architecture review

---

## Context

The YasarGold system manages three domains that are closely related but have fundamentally different invariants, ownership, and audit requirements:

1. **Inventory** — tracks the physical weight and location of gold (grams per bucket)
2. **Accounting (GL)** — tracks the monetary value of assets, expenses, and income in a double-entry ledger
3. **SafeBox** — tracks cash and physical valuables held in a secure location

As the system grew, it became tempting to let these domains share code directly: for example, having `InventoryAdjustmentService` create a `JournalEntry`, or having `SafeBoxService` read `InventoryBalance` directly. This pattern was observed and rejected.

## Decision

Inventory, Accounting (GL), and SafeBox are **independent Bounded Contexts**. Each context:
- Has its own models, services, and event log
- Communicates with other contexts through a **thin integration layer**, not direct imports
- Can be tested independently without the other contexts

```
┌─────────────────────────────────────────────────────────────────────┐
│  Inventory Context                                                  │
│    InventoryLedger, InventoryBalance, InventoryAdjustment           │
│    InventoryPostingService  (Single Writer)                         │
│    InventoryCountService, InventoryAdjustmentService                │
│    InventoryInvariantChecker, InventoryReconciliationReport         │
└────────────────────────┬────────────────────────────────────────────┘
                         │  InventoryAccountingService (integration layer)
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Accounting (GL) Context                                            │
│    JournalEntry, JournalEntryLine, Account, AccountingPeriod        │
│    JournalEntryBuilder, GLPostingService                            │
└────────────────────────┬────────────────────────────────────────────┘
                         │  (future: SafeBoxAccountingService)
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│  SafeBox Context                                                    │
│    SafeBox, SafeBoxEntry, SafeBoxBalance                            │
│    SafeBoxPostingService  (its own Single Writer)                   │
└─────────────────────────────────────────────────────────────────────┘
```

### Integration rules

| From → To         | Allowed path                                           | Forbidden                      |
|---|---|---|
| Inventory → GL    | Via `InventoryAccountingService` only                  | Direct `JournalEntry(...)` in inventory services |
| GL → Inventory    | Read-only query for reconciliation                     | Writing to `InventoryLedger` from GL             |
| SafeBox → GL      | Via `SafeBoxAccountingService` (future, same pattern)  | Direct GL write from SafeBox                     |
| Inventory → SafeBox | Not permitted — no direct dependency                | Any import across this boundary                  |
| SafeBox → Inventory | Not permitted                                       | Any import across this boundary                  |

### Why these three are separate contexts (not one big domain)

**Different invariants:**
- Inventory invariant: `SUM(InventoryLedger.weight_delta) == InventoryBalance.balance` (weight in grams)
- GL invariant: `SUM(debit) == SUM(credit)` per journal entry (monetary value)
- SafeBox invariant: physical item list matches registered entries (discrete items)

Combining these into one service would mean a single service must enforce all three invariants simultaneously, making it impossible to test any one of them in isolation.

**Different change rates:**
- Inventory changes on every sale/purchase (dozens per day)
- GL is often closed per period (monthly cut-off)
- SafeBox changes infrequently (deposits, withdrawals)

Coupling them means a SafeBox query would block on inventory locks, or a GL period-close would need to coordinate with live inventory writes.

**Different audit trails:**
- Inventory audit: weight per bucket over time (who moved gold, when)
- GL audit: monetary value per account per period (double-entry completeness)
- SafeBox audit: chain of custody for physical items

A single event log cannot serve all three without becoming unreadable to any one auditor.

## Enforcement

The separation is enforced at the code level by `test_architecture.py`:

- **RULE-3**: `test_inventory_services_do_not_import_journal_entry()` — inventory services may never import `JournalEntry` or `JournalEntryLine` directly
- The same rule will be extended for SafeBox once implemented

`InventoryAccountingService` is the only permitted crossing point from Inventory to GL. It is the **Anti-Corruption Layer** (ACL) in DDD terminology: it translates an inventory concept (`InventoryAdjustment`) into a GL concept (`JournalEntry`) without polluting either context with the other's model.

## What this means for future development

1. **New inventory document types** (transfer, manufacturing, reclass): add a new `post_*_to_gl()` method on `InventoryAccountingService`. Do not put GL logic in the document service.

2. **SafeBox implementation**: create `SafeBoxPostingService` as the Single Writer for its own ledger, mirroring the Inventory pattern. Create `SafeBoxAccountingService` as the integration layer to GL.

3. **Reconciliation**: `InventoryReconciliationReport` may query GL account balances (read-only) to build the four-way comparison (Ledger / Balance / GL / Physical Count). It does not write to GL.

4. **Phase 5 GL wiring**: `InventoryAccountingService._build_je()` will be the only place that constructs `JournalEntry` objects from inventory data. No other inventory file should ever import `JournalEntry`.

## Consequences

**Positive:**
- Each context can be tested independently with its own fixture set.
- A GL schema change (e.g. adding a new account type) does not require touching inventory services.
- The boundary is machine-checked: `test_architecture.py` catches violations at commit time.
- Aligns with the gold ERP's regulatory requirement that inventory weight records and financial records remain independently auditable.

**Negative / Trade-offs:**
- An adjustment that affects both inventory and GL requires two service calls (`InventoryAdjustmentService.post_adjustment()` then `InventoryAccountingService.post_adjustment_to_gl()`). The caller must coordinate both. This is handled in `InventoryAdjustmentService.post_adjustment()` — it calls both in sequence within the same request.
- The `gl_entry_id` foreign key on `InventoryAdjustment` is a deliberate soft link (nullable, no FK constraint to `journal_entry`). This keeps the tables independent at the DB level while still allowing correlation.

## Related

- ADR-001: Single Writer — same principle applied within the Inventory context
- ADR-005: Adjustment workflow — why adjustment does not create GL entries directly
- `test_architecture.py` RULE-3: machine enforcement of this boundary
