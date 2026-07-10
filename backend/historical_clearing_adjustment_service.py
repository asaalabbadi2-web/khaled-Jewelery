"""
HistoricalClearingAdjustmentService
=====================================
Admin-only mechanism for correcting historical clearing gaps.

Invariant enforced:
    GL (clearing account) == SafeBoxTransaction balance == SL-based pending

This service restores that invariant for legacy vouchers that were created
before AllocationService.validate() was enforced.

Lifecycle
---------
create()  →  status=pending   (no accounting written)
apply()   →  status=applied   (SBT + JE written atomically, with FOR UPDATE lock)
cancel()  →  status=cancelled (pending only)

Safety guarantees
-----------------
- apply() uses SELECT FOR UPDATE to prevent concurrent double-application.
- apply() raises AlreadyAppliedError if status != pending (idempotency).
- apply() rejects a second adjustment for the same (reference_voucher_id, type).
- Fields amount / safe_box_id / adjustment_type are immutable after creation.
- Both safe_box_id and account IDs are validated to exist before writing.

Usage (admin endpoint only)
---------------------------
    svc = HistoricalClearingAdjustmentService()

    adj = svc.create(
        safe_box_id=32,
        amount=6050.00,
        adjustment_type='historical_allocation_gap',
        reason='AV-2026-00133 creditted SafeBox 19,710 but SLs cover only 13,660 '
               'after rebuild reallocated 6,050 to AV236/AV237.',
        reference_voucher_number='AV-2026-00133',
        created_by='admin',
    )

    adj = svc.apply(
        adjustment_id=adj.id,
        applied_by='admin',
        clearing_account_id=777,
        contra_account_id=900,
    )
"""

from datetime import datetime

from models import (
    Account,
    HistoricalClearingAdjustment,
    JournalEntry,
    JournalEntryLine,
    SafeBox,
    SafeBoxTransaction,
    Voucher,
    db,
)


class AlreadyAppliedError(Exception):
    """Raised when apply() is called on an already-applied adjustment."""


class HistoricalClearingAdjustmentService:

    # ── Public API ────────────────────────────────────────────────────────────

    def create(
        self,
        *,
        safe_box_id: int,
        amount: float,
        adjustment_type: str,
        reason: str,
        created_by: str,
        reference_voucher_number: str | None = None,
    ) -> HistoricalClearingAdjustment:
        """Create a pending adjustment record (writes no accounting entries).

        Fields safe_box_id, amount, adjustment_type, and reference are
        immutable after this call — cancel and re-create to correct them.
        """
        if adjustment_type not in HistoricalClearingAdjustment.VALID_TYPES:
            raise ValueError(
                f'Invalid adjustment_type={adjustment_type!r}. '
                f'Must be one of: {sorted(HistoricalClearingAdjustment.VALID_TYPES)}'
            )
        if amount <= 0:
            raise ValueError(f'amount must be positive, got {amount}')

        if not SafeBox.query.get(safe_box_id):
            raise ValueError(f'SafeBox id={safe_box_id} not found')

        ref_voucher_id = None
        if reference_voucher_number:
            v = Voucher.query.filter_by(voucher_number=reference_voucher_number).first()
            if not v:
                raise ValueError(f'Voucher {reference_voucher_number!r} not found')
            ref_voucher_id = v.id

        adj = HistoricalClearingAdjustment(
            safe_box_id=safe_box_id,
            amount=round(float(amount), 2),
            adjustment_type=adjustment_type,
            reason=reason,
            created_by=created_by,
            reference_voucher_id=ref_voucher_id,
            reference_voucher_number=reference_voucher_number,
            status='pending',
        )
        db.session.add(adj)
        db.session.flush()
        return adj

    def apply(
        self,
        *,
        adjustment_id: int,
        applied_by: str,
        clearing_account_id: int,
        contra_account_id: int,
        apply_date: datetime | None = None,
    ) -> HistoricalClearingAdjustment:
        """Apply a pending adjustment atomically.

        Steps (all within the caller's transaction):
          1. Lock the row with SELECT FOR UPDATE.
          2. Guard: raise AlreadyAppliedError if status != pending.
          3. Validate: accounts exist, no duplicate applied adj for same ref+type.
          4. Create SafeBoxTransaction IN.
          5. Create JournalEntry + two JournalEntryLines (Dr / Cr).
          6. Mark adjustment applied and link the created records.

        The caller is responsible for db.session.commit() / rollback().
        """
        if apply_date is None:
            apply_date = datetime.utcnow()

        # ── 1. Lock row (prevents concurrent double-apply) ────────────────────
        adj = (
            HistoricalClearingAdjustment.query
            .with_for_update()
            .get(adjustment_id)
        )
        if adj is None:
            raise ValueError(f'HistoricalClearingAdjustment id={adjustment_id} not found')

        # ── 2. Idempotency guard ──────────────────────────────────────────────
        if adj.status == 'applied':
            raise AlreadyAppliedError(
                f'Adjustment #{adjustment_id} already applied '
                f'(sbt_id={adj.safe_box_transaction_id}, '
                f'je_id={adj.journal_entry_id}). '
                f'Applied by {adj.approved_by} at {adj.approved_at}.'
            )
        if adj.status != 'pending':
            raise ValueError(
                f'Adjustment #{adjustment_id} cannot be applied '
                f'(status={adj.status!r})'
            )

        # ── 3. Pre-apply validation ───────────────────────────────────────────
        self._validate_before_apply(adj, clearing_account_id, contra_account_id)

        amount = adj.amount
        ref_label = adj.reference_voucher_number or f'adj#{adj.id}'

        # ── 4. SafeBoxTransaction IN ──────────────────────────────────────────
        sbt = SafeBoxTransaction(
            safe_box_id=adj.safe_box_id,
            ref_type='historical_clearing_adjustment',
            ref_id=adj.id,
            direction='in',
            amount_cash=amount,
            created_by=applied_by,
        )
        db.session.add(sbt)
        db.session.flush()

        # ── 5. JournalEntry: Dr clearing / Cr contra ──────────────────────────
        je = JournalEntry(
            date=apply_date,
            description=(
                f'تصحيح تاريخي [{adj.adjustment_type}] مرجع {ref_label}: '
                f'{adj.reason[:120]}'
            ),
            reference_type='historical_clearing_adjustment',
            reference_id=adj.id,
            entry_type='manual',
            is_posted=True,
            posted_at=apply_date,
            posted_by=applied_by,
            created_by=applied_by,
        )
        db.session.add(je)
        db.session.flush()

        db.session.add(JournalEntryLine(
            journal_entry_id=je.id,
            account_id=clearing_account_id,
            cash_debit=amount,
            cash_credit=0.0,
            description=f'تصحيح تاريخي — Dr حساب المقاصة ({ref_label})',
        ))
        db.session.add(JournalEntryLine(
            journal_entry_id=je.id,
            account_id=contra_account_id,
            cash_debit=0.0,
            cash_credit=amount,
            description=f'تصحيح تاريخي — Cr حساب الفروق التاريخية ({ref_label})',
        ))

        # ── 6. Mark applied and link created records ──────────────────────────
        adj.status = 'applied'
        adj.approved_by = applied_by    # approved_by = applied_by (audit actor)
        adj.approved_at = apply_date
        adj.safe_box_transaction_id = sbt.id
        adj.journal_entry_id = je.id

        db.session.flush()
        return adj

    def cancel(
        self,
        *,
        adjustment_id: int,
        cancelled_by: str,
        reason: str,
    ) -> HistoricalClearingAdjustment:
        """Cancel a pending adjustment. Applied adjustments cannot be cancelled."""
        adj = (
            HistoricalClearingAdjustment.query
            .with_for_update()
            .get(adjustment_id)
        )
        if adj is None:
            raise ValueError(f'HistoricalClearingAdjustment id={adjustment_id} not found')
        if adj.status == 'applied':
            raise AlreadyAppliedError(
                f'Adjustment #{adjustment_id} is already applied and cannot be cancelled. '
                f'Contact the system administrator to reverse the SafeBoxTransaction and JournalEntry manually.'
            )
        if adj.status != 'pending':
            raise ValueError(
                f'Only pending adjustments can be cancelled (status={adj.status!r})'
            )
        adj.status = 'cancelled'
        adj.approved_by = cancelled_by
        adj.approved_at = datetime.utcnow()
        adj.reason = adj.reason + f'\n[CANCELLED by {cancelled_by}]: {reason}'
        db.session.flush()
        return adj

    # ── Internal validation ───────────────────────────────────────────────────

    def _validate_before_apply(
        self,
        adj: HistoricalClearingAdjustment,
        clearing_account_id: int,
        contra_account_id: int,
    ) -> None:
        """Raise ValueError for any condition that would produce invalid accounting."""

        # Accounts must exist
        for acc_id, label in (
            (clearing_account_id, 'clearing_account_id'),
            (contra_account_id, 'contra_account_id'),
        ):
            if not Account.query.get(acc_id):
                raise ValueError(f'{label}={acc_id} does not exist in the account table')

        # Clearing and contra must be different
        if clearing_account_id == contra_account_id:
            raise ValueError(
                'clearing_account_id and contra_account_id must be different accounts'
            )

        # Safe box must still exist
        if not SafeBox.query.get(adj.safe_box_id):
            raise ValueError(f'SafeBox id={adj.safe_box_id} not found')

        # No previous applied adjustment for the same reference + type
        # (prevents accidentally doubling the correction for the same voucher)
        if adj.reference_voucher_id:
            duplicate = (
                HistoricalClearingAdjustment.query
                .filter(
                    HistoricalClearingAdjustment.reference_voucher_id == adj.reference_voucher_id,
                    HistoricalClearingAdjustment.adjustment_type == adj.adjustment_type,
                    HistoricalClearingAdjustment.status == 'applied',
                    HistoricalClearingAdjustment.id != adj.id,
                )
                .first()
            )
            if duplicate:
                raise ValueError(
                    f'An applied adjustment (#{duplicate.id}) already exists for '
                    f'voucher {adj.reference_voucher_number!r} '
                    f'with type {adj.adjustment_type!r}. '
                    f'Apply is rejected to prevent double-correction.'
                )

        # Amount sanity (should have been enforced at create, but double-check)
        if adj.amount <= 0:
            raise ValueError(f'Adjustment amount must be positive, got {adj.amount}')
