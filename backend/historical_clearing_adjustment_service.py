"""
HistoricalClearingAdjustmentService
=====================================
Admin-only mechanism for correcting historical clearing gaps.

Invariant enforced:
    GL (clearing account) == SafeBoxTransaction balance == SL-based pending

This service restores that invariant for legacy vouchers that were created
before AllocationService.validate() was enforced.

Usage (admin endpoint only):
    svc = HistoricalClearingAdjustmentService()

    # Step 1: create (requires approval before apply)
    adj = svc.create(
        safe_box_id=32,
        amount=6050.00,
        adjustment_type='historical_allocation_gap',
        reason='AV-2026-00133 credited SafeBox 19,710 but SLs cover only 13,660 '
               'after rebuild reallocated 6,050 of IPs to AV236/AV237.',
        reference_voucher_number='AV-2026-00133',
        created_by='admin',
    )

    # Step 2: apply (creates SBT + JE atomically)
    adj = svc.apply(
        adjustment_id=adj.id,
        approved_by='admin',
        clearing_account_id=777,       # Dr (مدى GL account)
        contra_account_id=<suspense>,  # Cr (historical gap suspense)
    )
"""

from datetime import datetime

from models import (
    db,
    HistoricalClearingAdjustment,
    SafeBoxTransaction,
    JournalEntry,
    JournalEntryLine,
    Voucher,
)


class HistoricalClearingAdjustmentService:

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
        """Create a pending adjustment (does not touch DB accounting yet)."""
        if adjustment_type not in HistoricalClearingAdjustment.VALID_TYPES:
            raise ValueError(
                f'Invalid adjustment_type={adjustment_type!r}. '
                f'Must be one of: {sorted(HistoricalClearingAdjustment.VALID_TYPES)}'
            )
        if amount <= 0:
            raise ValueError(f'amount must be positive, got {amount}')

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
        approved_by: str,
        clearing_account_id: int,
        contra_account_id: int,
        apply_date: datetime | None = None,
    ) -> HistoricalClearingAdjustment:
        """Apply an approved adjustment atomically.

        Creates:
          1. SafeBoxTransaction IN on the clearing safe box
          2. Journal Entry: Dr clearing_account / Cr contra_account
          3. Marks adjustment as applied with approval metadata

        Raises ValueError if already applied or cancelled.
        """
        adj = HistoricalClearingAdjustment.query.get(adjustment_id)
        if adj is None:
            raise ValueError(f'HistoricalClearingAdjustment id={adjustment_id} not found')
        if adj.status != 'pending':
            raise ValueError(
                f'Adjustment id={adjustment_id} cannot be applied '
                f'(status={adj.status!r}, expected pending)'
            )

        if apply_date is None:
            apply_date = datetime.utcnow()

        amount = adj.amount

        # ── 1. SafeBoxTransaction IN ─────────────────────────────────────────
        sbt = SafeBoxTransaction(
            safe_box_id=adj.safe_box_id,
            ref_type='historical_clearing_adjustment',
            ref_id=adj.id,
            direction='in',
            amount_cash=amount,
            created_by=approved_by,
        )
        db.session.add(sbt)
        db.session.flush()

        # ── 2. Journal Entry (Dr clearing / Cr contra) ───────────────────────
        ref_label = adj.reference_voucher_number or f'adj#{adj.id}'
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
            posted_by=approved_by,
            created_by=approved_by,
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

        # ── 3. Mark applied ──────────────────────────────────────────────────
        adj.status = 'applied'
        adj.approved_by = approved_by
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
        """Cancel a pending adjustment (cannot cancel applied ones)."""
        adj = HistoricalClearingAdjustment.query.get(adjustment_id)
        if adj is None:
            raise ValueError(f'HistoricalClearingAdjustment id={adjustment_id} not found')
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
