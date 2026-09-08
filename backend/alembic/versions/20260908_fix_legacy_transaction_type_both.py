"""P4.2: Fix legacy transaction_type='both' — metadata/flags only

Revision ID: 20260908_fix_legacy_transaction_type_both
Revises: 20260907_memo_account_pair_constraints, bonus_phase7_scheduler_log_001
Create Date: 2026-09-08

يُصحِّح الـ flags الخاطئة على 5 حسابات تاريخية محددة بدقة.
التغيير: transaction_type='cash' + tracks_weight=False.
لا تغيير في أرقام الحسابات، لا إنشاء حسابات جديدة، لا تعديل أرصدة.

السياق (P4.1 + P4.1.5):
- هذه الحسابات ورثت transaction_type='both' من DB DEFAULT.
- tracks_weight=True على الأربعة غير 15 جاء خطأً لأن أسماءها تحتوي "ذهب".
- التحقيق أثبت أنها الجانب المالي (SAR) في منظومة dual-system:
    15   = صندوق النقدية    (cash register, رصيد 10,000 SAR)
    400  = مبيعات ذهب جديد  (revenue account, SAR)
    521  = تكلفة مبيعات     (COGS account, SAR)
    1200 = مخزون/عملاء أب   (inventory_24k + customers fallback, SAR)
    1220 = مخزون 21k        (inventory_21k fallback, SAR)

Pre-audit (P4.1.5):
  ✅ JE lines = 0 لكل حساب غير 15
  ✅ memo_account_id = NULL لكل الحسابات الخمسة
  ✅ balance_cash = 10,000 للحساب 15 (يُحافَظ عليه)
  ✅ لا AccountingMapping overrides
  ✅ لا أطفال

Migration محمية بـ:
  PRE-CHECK  → تتحقق من الحالة المتوقعة قبل أي تعديل
  IDEMPOTENT → تتخطى الحسابات الصحيحة مسبقاً بدل الفشل
  POST-CHECK → تتحقق من النتيجة بعد التعديل + سلامة الرصيد
  REPORT     → تطبع ما تغير قبل وبعد
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = '20260908_fix_legacy_transaction_type_both'
down_revision: Union[str, Sequence[str], None] = (
    '20260907_memo_account_pair_constraints',
    'bonus_phase7_scheduler_log_001',
)
branch_labels = None
depends_on = None

# ─── الحسابات المستهدفة بدقة ─────────────────────────────────────────────────
# الهيكل: account_number → {'allow_je': bool, 'allow_balance': bool}
# allow_je=False  → يتحقق أن لا JE lines (وإلا يرفض)
# allow_balance=True → لا يُخطئ إذا كان للحساب رصيد

_TARGETS = {
    '15':   {'allow_je': True,  'allow_balance': True},
    '400':  {'allow_je': False, 'allow_balance': False},
    '521':  {'allow_je': False, 'allow_balance': False},
    '1200': {'allow_je': False, 'allow_balance': False},
    '1220': {'allow_je': False, 'allow_balance': False},
}

# ─── هل الحساب يحتاج تصحيحاً؟ ───────────────────────────────────────────────

def _needs_fix(row) -> bool:
    return row.transaction_type != 'cash' or bool(row.tracks_weight)


# ─── PRE-CHECK ───────────────────────────────────────────────────────────────

def _pre_check(conn) -> dict[str, dict]:
    """
    يتحقق من كل حساب مستهدف ويعيد snapshot ما قبل التعديل.
    يرفع RuntimeError إذا وجد أي تناقض مع الحالة المتوقعة.
    """
    snapshot = {}
    for acc_num, constraints in _TARGETS.items():
        row = conn.execute(
            text("""
                SELECT id, transaction_type, tracks_weight,
                       balance_cash, balance_21k, memo_account_id
                FROM account WHERE account_number = :n
            """),
            {'n': acc_num},
        ).fetchone()

        if row is None:
            raise RuntimeError(
                f'PRE-CHECK FAIL: الحساب {acc_num} غير موجود في DB — '
                'تحقق من أن النظام مشغَّل على البيئة الصحيحة'
            )

        # idempotent: حساب صحيح مسبقاً → لا فحوصات إضافية
        if not _needs_fix(row):
            snapshot[acc_num] = dict(row._mapping) | {'_skip': True}
            continue

        # حالة غير متوقعة: transaction_type ليس 'both' ولا 'cash'
        if row.transaction_type not in ('both', 'cash'):
            raise RuntimeError(
                f'PRE-CHECK FAIL: الحساب {acc_num} لديه '
                f"transaction_type='{row.transaction_type}' — "
                'يُتوقع both أو cash فقط'
            )

        # رابط موازٍ غير متوقع
        if row.memo_account_id is not None:
            raise RuntimeError(
                f'PRE-CHECK FAIL: الحساب {acc_num} لديه '
                f'memo_account_id={row.memo_account_id} غير متوقع — '
                'راجع يدوياً قبل التصحيح'
            )

        # JE history غير متوقع
        if not constraints['allow_je']:
            je_count = conn.execute(
                text('SELECT COUNT(*) FROM journal_entry_line WHERE account_id = :id'),
                {'id': row.id},
            ).scalar()
            if je_count > 0:
                raise RuntimeError(
                    f'PRE-CHECK FAIL: الحساب {acc_num} له {je_count} سطر قيد — '
                    'الـ P4.1.5 أثبتت صفراً؛ قد يكون الوضع تغير؛ راجع يدوياً'
                )

        # رصيد غير متوقع (للحسابات غير 15)
        if not constraints['allow_balance']:
            cash = float(row.balance_cash or 0)
            if abs(cash) > 0.001:
                raise RuntimeError(
                    f'PRE-CHECK FAIL: الحساب {acc_num} له رصيد نقدي {cash} — '
                    'غير متوقع؛ راجع يدوياً'
                )

        snapshot[acc_num] = dict(row._mapping) | {'_skip': False}

    return snapshot


# ─── APPLY UPDATE ─────────────────────────────────────────────────────────────

def _apply_update(conn, snapshot: dict[str, dict]) -> int:
    """
    يُطبِّق UPDATE فقط على الحسابات التي تحتاج تصحيحاً.
    يعيد عدد الصفوف المُعدَّلة.
    """
    to_fix = [n for n, s in snapshot.items() if not s.get('_skip')]
    if not to_fix:
        return 0

    result = conn.execute(
        text("""
            UPDATE account
            SET transaction_type = 'cash',
                tracks_weight     = FALSE
            WHERE account_number IN :numbers
              AND (transaction_type != 'cash' OR tracks_weight = TRUE)
        """),
        {'numbers': tuple(to_fix)},
    )
    return result.rowcount


# ─── POST-CHECK ───────────────────────────────────────────────────────────────

def _post_check(conn, snapshot: dict[str, dict]) -> None:
    """
    يتحقق من النتيجة بعد التعديل:
      1. كل حساب مستهدف: transaction_type='cash' + tracks_weight=False
      2. الحساب 15: رصيد لم يتغير
      3. Invariant عام: لا حساب non-7xxx له tracks_weight=True + type='gold'
    """
    for acc_num in _TARGETS:
        post = conn.execute(
            text("""
                SELECT transaction_type, tracks_weight, balance_cash
                FROM account WHERE account_number = :n
            """),
            {'n': acc_num},
        ).fetchone()

        if post is None:
            raise RuntimeError(f'POST-CHECK FAIL: الحساب {acc_num} اختفى بعد التعديل!')

        if post.transaction_type != 'cash':
            raise RuntimeError(
                f'POST-CHECK FAIL: الحساب {acc_num} ما زال '
                f"transaction_type='{post.transaction_type}'"
            )

        if post.tracks_weight:
            raise RuntimeError(
                f'POST-CHECK FAIL: الحساب {acc_num} ما زال tracks_weight=True'
            )

        # سلامة رصيد الحساب 15
        if acc_num == '15' and '15' in snapshot and not snapshot['15'].get('_skip'):
            pre_cash  = float(snapshot['15'].get('balance_cash') or 0)
            post_cash = float(post.balance_cash or 0)
            if abs(post_cash - pre_cash) > 0.001:
                raise RuntimeError(
                    f'POST-CHECK FAIL: رصيد الحساب 15 تغيَّر! '
                    f'قبل={pre_cash:.3f} بعد={post_cash:.3f}'
                )

    # Invariant: لا حساب non-7xxx له gold + tracks_weight=True
    violations = conn.execute(text("""
        SELECT account_number, name, transaction_type, tracks_weight
        FROM account
        WHERE account_number NOT LIKE '7%'
          AND transaction_type = 'gold'
          AND tracks_weight = TRUE
    """)).fetchall()

    if violations:
        details = '; '.join(
            f"{r.account_number}({r.name})" for r in violations
        )
        raise RuntimeError(
            f'INVARIANT FAIL: حسابات non-7xxx لها gold+tracks_weight=True: {details}'
        )


# ─── REPORT ───────────────────────────────────────────────────────────────────

def _print_report(snapshot: dict[str, dict], rows_changed: int, conn) -> None:
    divider = '─' * 60
    print(f'\n{divider}')
    print('  P4.2 — Fix legacy transaction_type=both — REPORT')
    print(divider)
    for acc_num in _TARGETS:
        pre = snapshot.get(acc_num, {})
        if pre.get('_skip'):
            print(f'  {acc_num}: ✓ بدون تغيير (كان صحيحاً مسبقاً)')
            continue
        post = conn.execute(
            text('SELECT transaction_type, tracks_weight, balance_cash '
                 'FROM account WHERE account_number = :n'),
            {'n': acc_num},
        ).fetchone()
        pre_type = pre.get('transaction_type', '?')
        pre_tw   = pre.get('tracks_weight', '?')
        print(
            f'  {acc_num}: '
            f'{pre_type}+tw={pre_tw} '
            f'→ {post.transaction_type}+tw={post.tracks_weight}'
            + (f'  [رصيد محفوظ: {float(post.balance_cash or 0):.3f}]'
               if acc_num == '15' else '')
        )
    print(f'\n  الصفوف المُعدَّلة: {rows_changed}')
    print(divider)


# ─── UPGRADE / DOWNGRADE ─────────────────────────────────────────────────────

def upgrade() -> None:
    conn = op.get_bind()

    snapshot     = _pre_check(conn)
    rows_changed = _apply_update(conn, snapshot)
    _post_check(conn, snapshot)
    _print_report(snapshot, rows_changed, conn)


def downgrade() -> None:
    raise NotImplementedError(
        'P4.2 downgrade غير متاح — migration بيانات بلا undo آمن.\n'
        'إذا احتجت التراجع، استخدم تقرير الـ upgrade (snapshot قبل/بعد) '
        'وأعد ضبط transaction_type يدوياً بعد مراجعة.'
    )
