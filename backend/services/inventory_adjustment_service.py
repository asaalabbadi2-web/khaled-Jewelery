"""InventoryAdjustmentService — creates and posts inventory adjustments.

Two entry points:

1. create_from_session(session) — generates an InventoryAdjustment from all
   non-zero variances in an approved InventoryCountSession.
   Called by InventoryCountService.approve_session() — the caller owns the
   transaction and commits only once at the end.

2. create_manual(branch_id, lines, ...) — standalone adjustment for write-offs,
   corrections, etc., without a count session.

Posting always goes through InventoryPostingService, never directly to the Ledger.

Flow for count-based adjustment:
    approve_session()
        ↓
    create_from_session()   ← this module
        ↓
    InventoryPostingService.post(adjustment)
        ↓
    InventoryLedger  +  InventoryBalance  (atomic)
        ↓
    _stub_gl_entry()        ← placeholder; replaced in Phase 5
"""
from __future__ import annotations
from datetime import datetime
from typing import List


class InventoryAdjustmentService:

    @classmethod
    def create_from_session(
        cls,
        session: 'InventoryCountSession',
        reason: str = '',
        notes: str = '',
        created_by: str = '',
    ) -> 'InventoryAdjustment | None':
        """Build an InventoryAdjustment from the session's non-zero variances.

        Returns None if every count line has zero variance (nothing to post).
        The adjustment is left in 'draft' status — call post_adjustment() to
        write to the Ledger.
        """
        from models import db, InventoryAdjustment, InventoryAdjustmentLine, InventoryCountLine

        lines_with_variance = (
            InventoryCountLine.query
            .filter_by(session_id=session.id)
            .filter(InventoryCountLine.variance != 0)
            .filter(InventoryCountLine.variance.isnot(None))
            .all()
        )

        if not lines_with_variance:
            return None

        adj = InventoryAdjustment(
            session_id=session.id,
            branch_id=session.branch_id,
            adjustment_type='count_variance',
            status='draft',
            reason=reason or 'OTHER',
            notes=notes or None,
            created_by=created_by or session.approved_by or 'system',
            created_at=datetime.now(),  # clock-guard: TIME-001
        )
        db.session.add(adj)
        db.session.flush()

        for count_line in lines_with_variance:
            adj_line = InventoryAdjustmentLine(
                adjustment_id=adj.id,
                branch_id=count_line.branch_id,
                category_id=count_line.category_id,
                karat=count_line.karat,
                expected_weight=float(count_line.expected_weight or 0.0),
                counted_weight=float(count_line.counted_weight or 0.0),
                variance_weight=round(float(count_line.variance or 0.0), 4),
            )
            db.session.add(adj_line)

        db.session.flush()
        return adj

    @classmethod
    def post_adjustment(cls, adjustment: 'InventoryAdjustment') -> list:
        """Post the adjustment through InventoryPostingService.

        Writes InventoryLedger entries and updates InventoryBalance.
        Marks adjustment as 'posted'.
        Calls the GL stub (Phase 5 will replace with real GL creation).
        Returns new InventoryLedger rows.
        """
        from services.inventory_posting_service import InventoryPostingService

        if adjustment.status == 'posted':
            return []

        entries = InventoryPostingService.post(adjustment)
        from services.inventory_accounting_service import InventoryAccountingService
        InventoryAccountingService.post_adjustment_to_gl(adjustment)
        return entries

    @classmethod
    def create_manual(
        cls,
        branch_id: int | None,
        lines_data: List[dict],
        reason: str,
        created_by: str,
        auto_post: bool = False,
    ) -> 'InventoryAdjustment':
        """Create a standalone manual adjustment.

        lines_data items must have: category_id, karat, variance_weight
        Optional: expected_weight, counted_weight, notes

        If auto_post=True, immediately posts through InventoryPostingService.
        """
        from models import db, InventoryAdjustment, InventoryAdjustmentLine

        adj = InventoryAdjustment(
            branch_id=branch_id,
            adjustment_type='manual',
            status='draft',
            reason=reason,
            created_by=created_by,
            created_at=datetime.now(),  # clock-guard: TIME-001
        )
        db.session.add(adj)
        db.session.flush()

        for d in lines_data:
            variance = float(d.get('variance_weight', 0.0))
            if variance == 0.0:
                continue
            line = InventoryAdjustmentLine(
                adjustment_id=adj.id,
                branch_id=branch_id,
                category_id=d.get('category_id'),
                karat=float(d['karat']),
                expected_weight=float(d.get('expected_weight', 0.0)),
                counted_weight=float(d.get('counted_weight', 0.0)),
                variance_weight=round(variance, 4),
                notes=d.get('notes'),
            )
            db.session.add(line)

        db.session.flush()

        if auto_post:
            adj.posted_by = created_by
            cls.post_adjustment(adj)

        return adj

