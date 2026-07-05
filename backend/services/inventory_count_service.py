"""InventoryCountService — manages physical inventory count sessions.

Lifecycle:
    open_session()   → status='open',     snapshot_ledger_id captured
    start_counting() → status='counting'  (optional state; lines can be added any time)
    record_count()   → update InventoryCountLine.counted_weight + variance
    close_session()  → status='closed'    (all lines must have counted_weight)
    approve_session() → status='approved'  (Phase 4: triggers GL adjustment)

snapshot_ledger_id:
    Captured once at open time as MAX(InventoryLedger.id).
    This is the Ledger cutoff — only entries up to this ID contribute to
    expected_weight on count lines.  Entries posted after this ID (during
    the count) are excluded from the expected calculation.
"""
from __future__ import annotations
from datetime import datetime
from typing import List


class InventoryCountService:

    # ── Open ──────────────────────────────────────────────────────────────────

    @classmethod
    def open_session(cls, branch_id: int | None, opened_by: str, notes: str = '', blind_count: bool = True) -> 'InventoryCountSession':
        """Open a new count session and freeze the Ledger snapshot.

        Raises ValueError if another open/counting session exists for this branch.
        """
        from models import db, InventoryCountSession, InventoryLedger
        from sqlalchemy import func

        # Guard: only one active session per branch
        active = InventoryCountSession.query.filter(
            InventoryCountSession.branch_id == branch_id,
            InventoryCountSession.status.in_(['open', 'counting']),
        ).first()
        if active:
            raise ValueError(
                f'جلسة جرد مفتوحة بالفعل (#{active.id}) لهذا الفرع — '
                f'أغلقها أولاً قبل فتح جلسة جديدة.'
            )

        # Freeze the Ledger cutoff
        max_id = db.session.query(func.max(InventoryLedger.id)).scalar() or 0

        session = InventoryCountSession(
            branch_id=branch_id,
            status='open',
            snapshot_ledger_id=max_id,
            blind_count=blind_count,
            opened_by=opened_by,
            opened_at=datetime.now(),
            notes=notes or None,
        )
        db.session.add(session)
        db.session.flush()
        return session

    # ── Populate lines from Balance snapshot ──────────────────────────────────

    @classmethod
    def populate_lines(cls, session: 'InventoryCountSession') -> List['InventoryCountLine']:
        """Create one InventoryCountLine per InventoryBalance bucket for this branch.

        Reads from InventoryBalance (the snapshot at session.snapshot_ledger_id).
        Lines are only created once — safe to call multiple times (idempotent).
        """
        from models import db, InventoryBalance, InventoryCountLine

        if session.status not in ('open', 'counting'):
            raise ValueError(f'لا يمكن ملء الأسطر — حالة الجلسة: {session.status}')

        query = InventoryBalance.query
        if session.branch_id is not None:
            query = query.filter_by(branch_id=session.branch_id)

        created: List[InventoryCountLine] = []
        for bal in query.all():
            exists = InventoryCountLine.query.filter_by(
                session_id=session.id,
                category_id=bal.category_id,
                karat=bal.karat,
            ).first()
            if exists:
                continue

            line = InventoryCountLine(
                session_id=session.id,
                branch_id=bal.branch_id,
                category_id=bal.category_id,
                karat=bal.karat,
                expected_weight=round(float(bal.balance or 0.0), 4),
                expected_ledger_id=bal.snapshot_max_ledger_id,
            )
            db.session.add(line)
            created.append(line)

        if created:
            db.session.flush()
        return created

    # ── Record physical count ──────────────────────────────────────────────────

    @classmethod
    def record_count(
        cls,
        session: 'InventoryCountSession',
        category_id: int | None,
        karat: float,
        counted_weight: float,
        counted_by: str = '',
    ) -> 'InventoryCountLine':
        """Record (or update) the physical count for one line.

        Creates the line if it doesn't exist (allows counting items not in Balance).
        """
        from models import db, InventoryCountLine

        if session.status not in ('open', 'counting'):
            raise ValueError(f'لا يمكن تسجيل عد — حالة الجلسة: {session.status}')

        line = InventoryCountLine.query.filter_by(
            session_id=session.id,
            category_id=category_id,
            karat=karat,
        ).first()

        if line is None:
            line = InventoryCountLine(
                session_id=session.id,
                branch_id=session.branch_id,
                category_id=category_id,
                karat=karat,
                expected_weight=0.0,
                expected_ledger_id=None,
            )
            db.session.add(line)

        line.counted_weight = round(float(counted_weight), 4)
        line.variance = round(line.counted_weight - float(line.expected_weight or 0.0), 4)
        line.counted_by = counted_by or None
        line.counted_at = datetime.now()

        if session.status == 'open':
            session.status = 'counting'

        db.session.flush()
        return line

    # ── Close ─────────────────────────────────────────────────────────────────

    @classmethod
    def close_session(cls, session: 'InventoryCountSession') -> 'InventoryCountSession':
        """Close the session.

        All lines with expected_weight > 0 must have a counted_weight.
        Lines with only surplus (expected=0, counted>0) are allowed.
        """
        from models import InventoryCountLine

        if session.status not in ('open', 'counting'):
            raise ValueError(f'لا يمكن إغلاق جلسة بحالة: {session.status}')

        uncounted = InventoryCountLine.query.filter_by(
            session_id=session.id,
        ).filter(
            InventoryCountLine.expected_weight > 0,
            InventoryCountLine.counted_weight.is_(None),
        ).count()

        if uncounted > 0:
            raise ValueError(
                f'يوجد {uncounted} سطر لم يُعدّ بعد — أكمل العد قبل الإغلاق.'
            )

        session.status = 'closed'
        session.closed_at = datetime.now()
        return session

    # ── Approve ───────────────────────────────────────────────────────────────

    @classmethod
    def approve_session(
        cls,
        session: 'InventoryCountSession',
        approved_by: str,
        adjustment_reason: str = '',
    ) -> tuple:
        """Approve the closed session.

        Flow (Phase 4):
            1. Mark session as approved
            2. Create InventoryAdjustment from non-zero variances
            3. Post through InventoryPostingService → Ledger → Balance
            4. GL stub called (Phase 5 replaces with real JE)

        Returns (session, adjustment) — adjustment is None if all variances were zero.
        All steps run in the caller's transaction; caller is responsible for commit.
        """
        if session.status != 'closed':
            raise ValueError(f'يجب إغلاق الجلسة أولاً — الحالة الحالية: {session.status}')

        session.status = 'approved'
        session.approved_by = approved_by
        session.approved_at = datetime.now()

        from services.inventory_adjustment_service import InventoryAdjustmentService
        adjustment = InventoryAdjustmentService.create_from_session(
            session,
            reason=adjustment_reason or 'تسوية جرد',
            created_by=approved_by,
        )
        if adjustment is not None:
            adjustment.posted_by = approved_by
            InventoryAdjustmentService.post_adjustment(adjustment)

        return session, adjustment
