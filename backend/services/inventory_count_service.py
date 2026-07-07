"""InventoryCountService — manages physical inventory count sessions.

Lifecycle:
    open_session()    → status='open',     snapshot_ledger_id captured
    start_counting()  → status='counting'  (optional state; lines can be added any time)
    record_count()    → update InventoryCountLine.counted_weight + variance
    close_session()   → status='closed'    (see policy below)
    approve_session() → status='approved'  (triggers GL adjustment or opening entries)

Close Policy (enforced here, not in routes):
    session_type='opening':  ALL lines must be counted — no partial close.
        Rationale: opening balance is a one-time foundation; a partial opening
        corrupts the starting point for all future periodic counts.
    session_type='periodic': partial close allowed with force=True.
        Rationale: items may be at jeweler, pledged, or otherwise absent.
        Uncounted lines appear in reconciliation as gaps.

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
    def open_session(
        cls,
        branch_id: int | None,
        opened_by: str,
        notes: str = '',
        blind_count: bool = True,
        session_type: str = 'periodic',
    ) -> 'InventoryCountSession':
        """Open a new count session and freeze the Ledger snapshot.

        session_type='opening': first-time stock entry. Forced blind_count=False
        (counter enters real weights freely); on approval posts InventoryLedger
        rows with movement_type='opening' instead of creating an InventoryAdjustment.

        Raises ValueError if another open/counting session exists for this branch.
        Raises ValueError if session_type='opening' and an approved opening session
        already exists for this branch (one opening session per branch, ever).
        """
        from models import db, InventoryCountSession, InventoryLedger
        from sqlalchemy import func

        if session_type not in ('periodic', 'opening'):
            raise ValueError(f'session_type غير صالح: {session_type}')

        # Opening session has no expected values to hide — blind count makes no sense
        if session_type == 'opening':
            blind_count = False

        # Guard: only one active session per branch
        active = InventoryCountSession.query.filter(
            InventoryCountSession.branch_id == branch_id,
            InventoryCountSession.status.in_(['open', 'counting']),
        ).first()
        if active:
            raise ValueError(
                f'جلسة جرد مفتوحة بالفعل (#{active.id}) لهذا الفرع — '
                f'أغلقها أولاً قبل فتح جلسة جد��دة.'
            )

        # Guard: only one APPROVED opening session per branch
        if session_type == 'opening':
            prior = InventoryCountSession.query.filter(
                InventoryCountSession.branch_id == branch_id,
                InventoryCountSession.session_type == 'opening',
                InventoryCountSession.status == 'approved',
            ).first()
            if prior:
                raise ValueError(
                    f'يوجد رصيد افتتاحي معتمد بالفعل لهذا الفرع (جلسة #{prior.id}). '
                    f'الجرد الافتتاحي ينفَّذ مرة واحدة فقط ��ند بدء تشغيل النظام. '
                    f'لتصحيح الأرصدة، استخدم جلس�� جرد دوري.'
                )

        # Freeze the Ledger cutoff (0 for opening — no prior ledger entries expected)
        max_id = db.session.query(func.max(InventoryLedger.id)).scalar() or 0

        session = InventoryCountSession(
            branch_id=branch_id,
            status='open',
            session_type=session_type,
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

    # ── Populate opening lines from Category catalog ──────────────────────────

    @classmethod
    def populate_opening_lines(cls, session: 'InventoryCountSession') -> List['InventoryCountLine']:
        """For opening sessions: create one InventoryCountLine per (category, karat).

        If the Category row has a karat set, use it (e.g. Category("خاتم 21", karat='21')).
        Otherwise create lines for all standard karats so the employee fills in each one.
        Lines with counted_weight=0.0 are valid — they mean "we have none of this type."
        Safe to call multiple times (idempotent).
        """
        from models import db, Category, InventoryCountLine

        STANDARD_KARATS = [18.0, 21.0, 22.0, 24.0]

        if session.status not in ('open', 'counting'):
            raise ValueError(f'لا يمكن ملء الأسطر — حالة الجلسة: {session.status}')

        created: List[InventoryCountLine] = []
        for cat in Category.query.order_by(Category.name).all():
            cat_karat: float | None = None
            if cat.karat:
                try:
                    cat_karat = float(cat.karat)
                except (ValueError, TypeError):
                    cat_karat = None

            karats = [cat_karat] if cat_karat else STANDARD_KARATS

            for karat in karats:
                exists = InventoryCountLine.query.filter_by(
                    session_id=session.id,
                    category_id=cat.id,
                    karat=karat,
                ).first()
                if exists:
                    continue

                line = InventoryCountLine(
                    session_id=session.id,
                    branch_id=session.branch_id,
                    category_id=cat.id,
                    karat=karat,
                    expected_weight=0.0,
                    expected_ledger_id=None,
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
    def close_session(
        cls,
        session: 'InventoryCountSession',
        force: bool = False,
        zero_uncounted: bool = False,
    ) -> int:
        """Close the session. Returns count of lines that were zeroed or left uncounted.

        Close policy:
        - opening + zero_uncounted=True:  auto-set uncounted lines to 0 then close.
        - opening + zero_uncounted=False: ALL lines must have been counted explicitly.
        - periodic + force=True:          partial close allowed (uncounted lines stay NULL).
        - periodic + force=False:         rejects if any uncounted lines exist.
        """
        from models import db, InventoryCountLine

        if session.status not in ('open', 'counting'):
            raise ValueError(f'لا يمكن إغلاق جلسة بحالة: {session.status}')

        session_type = getattr(session, 'session_type', 'periodic') or 'periodic'

        uncounted_q = InventoryCountLine.query.filter_by(
            session_id=session.id,
        ).filter(
            InventoryCountLine.counted_weight.is_(None),
        )
        uncounted = uncounted_q.count()

        if uncounted > 0:
            if session_type == 'opening' and zero_uncounted:
                # Employee confirmed "register remaining as zero" — set them explicitly
                for ln in uncounted_q.all():
                    ln.counted_weight = 0.0
                    ln.variance = round(0.0 - float(ln.expected_weight or 0.0), 4)
                    ln.counted_at = datetime.now()
                db.session.flush()
                uncounted = 0
            elif session_type == 'opening':
                raise ValueError(
                    f'جلسة الرصيد الافتتاحي تتطلب عدّ جميع الأصناف — '
                    f'يوجد {uncounted} صنف لم يُعدّ. '
                    f'أدخل الوزن الفعلي أو اضغط "سجّل الباقي كصفر" إذا لم يتوفر.'
                )
            elif not force:
                raise ValueError(
                    f'يوجد {uncounted} صنف لم يُعدّ — أكمل العدّ أو استخدم "إغلاق مع تحذير" '
                    f'إذا كانت بعض القطع خارج المحل.'
                )

        session.status = 'closed'
        session.closed_at = datetime.now()
        return uncounted

    # ── Approve ───────────────────────────────────────────────────────────────

    @classmethod
    def approve_session(
        cls,
        session: 'InventoryCountSession',
        approved_by: str,
        adjustment_reason: str = '',
        adjustment_note: str = '',
    ) -> tuple:
        """Approve the closed session.

        session_type='periodic' flow (Phase 4):
            1. Mark session as approved
            2. Create InventoryAdjustment from non-zero variances
            3. Post through InventoryPostingService → Ledger → Balance

        session_type='opening' flow:
            1. Mark session as approved
            2. Post each counted line directly as InventoryLedger(opening_balance, opening)
            3. No InventoryAdjustment created (nothing to adjust against)

        Returns (session, adjustment) — adjustment is None for opening sessions or
        when all periodic variances are zero.
        All steps run in the caller's transaction; caller is responsible for commit.
        """
        if session.status != 'closed':
            raise ValueError(f'يجب إغلاق الجلسة أولاً — الحالة الحالية: {session.status}')

        session.status = 'approved'
        session.approved_by = approved_by
        session.approved_at = datetime.now()

        session_type = getattr(session, 'session_type', 'periodic') or 'periodic'

        if session_type == 'opening':
            cls._post_opening_balances(session, approved_by)
            return session, None

        from services.inventory_adjustment_service import InventoryAdjustmentService
        adjustment = InventoryAdjustmentService.create_from_session(
            session,
            reason=adjustment_reason or 'OTHER',
            notes=adjustment_note,
            created_by=approved_by,
        )
        if adjustment is not None:
            adjustment.posted_by = approved_by
            InventoryAdjustmentService.post_adjustment(adjustment)

        return session, adjustment

    @classmethod
    def _post_opening_balances(cls, session: 'InventoryCountSession', posted_by: str) -> None:
        """Post each counted line as an opening-balance Ledger entry.

        The opening session declares "what we count IS the truth." Any prior
        balance (e.g. from a backfill or earlier entries) is zeroed out first
        via a reversal entry, then the counted weight is posted as the new truth.

        Two entry types per affected bucket:
          'opening_reversal' — cancels existing balance (idempotent, skipped if zero)
          'opening_balance'  — posts counted weight as the new starting point

        Both use the same (source_id=session.id, source_line_id=ln.id), which
        is safe because source_type differs → no UniqueConstraint collision.
        """
        from models import db, InventoryCountLine, InventoryLedger, InventoryBalance

        lines = InventoryCountLine.query.filter_by(session_id=session.id).all()
        for ln in lines:
            if ln.counted_weight is None:
                continue

            counted = round(float(ln.counted_weight), 4)

            # ── Step 1: Reverse existing balance so opening count becomes the sole truth ──
            existing = InventoryBalance.query.filter_by(
                branch_id=ln.branch_id,
                category_id=ln.category_id,
                karat=ln.karat,
            ).first()
            prior_balance = round(float(existing.balance), 4) if existing else 0.0

            reversal_exists = InventoryLedger.query.filter_by(
                source_type='opening_reversal',
                source_id=session.id,
                source_line_id=ln.id,
                movement_type='opening',
            ).first()
            if not reversal_exists and prior_balance != 0.0:
                db.session.add(InventoryLedger(
                    source_type='opening_reversal',
                    source_id=session.id,
                    source_line_id=ln.id,
                    movement_type='opening',
                    branch_id=ln.branch_id,
                    category_id=ln.category_id,
                    karat=ln.karat,
                    weight_delta=-prior_balance,
                    posted_by=posted_by,
                    notes=f'إلغاء رصيد سابق — جلسة افتتاحية #{session.id}',
                ))

            # ── Step 2: Post counted weight as opening balance ────────────────────────
            balance_exists = InventoryLedger.query.filter_by(
                source_type='opening_balance',
                source_id=session.id,
                source_line_id=ln.id,
                movement_type='opening',
            ).first()
            if not balance_exists and counted != 0.0:
                db.session.add(InventoryLedger(
                    source_type='opening_balance',
                    source_id=session.id,
                    source_line_id=ln.id,
                    movement_type='opening',
                    branch_id=ln.branch_id,
                    category_id=ln.category_id,
                    karat=ln.karat,
                    weight_delta=counted,
                    posted_by=posted_by,
                    notes=f'رصيد افتتاحي — جلسة #{session.id}',
                ))

        db.session.flush()

        # Rebuild InventoryBalance: apply all opening entries (reversal + balance)
        from services.inventory_posting_service import InventoryPostingService
        InventoryPostingService.rebuild_balance_for_session(session)
