"""InventoryAccountingService — GL integration layer for inventory movements.

Architectural boundary:
    InventoryAdjustmentService  (knows about variances)
            ↓
    InventoryAccountingService  (knows about Chart of Accounts)
            ↓
    JournalEntryBuilder         (Phase 5: builds JE lines per bucket)
            ↓
    JournalEntry                (persisted GL record)

This separation means:
  - InventoryAdjustmentService never imports Account or JournalEntry
  - New inventory document types (transfer, manufacturing, reclass) each
    call InventoryAccountingService with their own logic — no GL code leaks
    into the business layer
  - GL mapping (which account per karat/category) lives in one place

Phase 5 status:
    post_adjustment_to_gl() is a stub that logs intent.
    Phase 5 will replace the stub body with real JE creation using
    the accounting mapping table (AccountingMapping / Settings).

Public API (stable — Phase 5 fills the bodies):
    InventoryAccountingService.post_adjustment_to_gl(adjustment)
    InventoryAccountingService.post_opening_entry_to_gl(opening)   # future
    InventoryAccountingService.post_transfer_to_gl(transfer)       # future
"""
from __future__ import annotations
from typing import Optional

from services.inventory_accounting_policy import (
    InventoryAccountingPolicy,
    DefaultInventoryPolicy,
)


class InventoryAccountingService:

    @classmethod
    def post_adjustment_to_gl(
        cls,
        adjustment,
        policy: Optional[InventoryAccountingPolicy] = None,
    ) -> None:
        """Create GL journal entries for an inventory adjustment.

        Args:
            adjustment: InventoryAdjustment instance (status='posted')
            policy:     InventoryAccountingPolicy that decides which accounts
                        to use per line. Defaults to DefaultInventoryPolicy.

        Phase 5 implementation will:
            1. Resolve policy (default if None)
            2. Per line: call policy.accounts_for_line(line) → AccountPair
            3. Build JournalEntry + JournalEntryLine rows
            4. Post the JE (is_posted=True inside same transaction)
            5. Set adjustment.gl_entry_id = je.id
        """
        if policy is None:
            policy = DefaultInventoryPolicy()

        lines = list(getattr(adjustment, 'lines', None) or [])
        total_variance = sum(float(getattr(l, 'variance_weight', 0) or 0) for l in lines)

        print(
            f'[GL STUB Phase 5] Adjustment #{adjustment.id} ready for GL posting — '
            f'branch={adjustment.branch_id}, '
            f'lines={len(lines)}, '
            f'net_variance={round(total_variance, 4)}g, '
            f'policy={policy.label()}, '
            f'reason={adjustment.reason!r}. '
            f'Replace this stub in Phase 5 with InventoryAccountingService._build_je().'
        )
        # Phase 5: uncomment and implement
        # je = cls._build_je(adjustment, policy)
        # adjustment.gl_entry_id = je.id

    # ── Phase 5 skeleton (not active) ─────────────────────────────────────────

    @classmethod
    def _build_je(cls, adjustment) -> object:  # → JournalEntry
        """Build and post a JournalEntry for an adjustment.

        Each InventoryAdjustmentLine becomes two JE lines:
            Positive variance:
                DR  inventory_account     variance_weight (weight debit)
                CR  adjustment_account    variance_weight (weight credit)
            Negative variance:
                DR  adjustment_account    |variance_weight| (cash/weight debit)
                CR  inventory_account     |variance_weight| (weight credit)

        Account lookup order:
            1. AccountingMapping keyed by (category_id, karat)
            2. Settings.default_inventory_account_id as fallback
            3. Hard-coded fallback (raises if missing)
        """
        raise NotImplementedError(
            'InventoryAccountingService._build_je() is Phase 5 — not yet implemented.'
        )
