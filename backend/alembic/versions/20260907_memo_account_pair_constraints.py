"""P2: memo_account_id pair integrity constraints

Revision ID: 20260907_memo_account_pair_constraints
Revises: 20260519_goal_bonus_fields, reservation_outbox_001
Create Date: 2026-09-07

يُضيف هذا الـ migration طبقتين من الحماية على علاقة الحسابات المزدوجة
(financial ↔ memo):

P2.1 — UNIQUE(memo_account_id):
  يضمن أن لا حسابَين يشيران لنفس الشريك الموازي (1:1 على مستوى DB).
  NULLs مسموح بها (حسابات بلا موازٍ)؛ PostgreSQL يعامل NULL ≠ NULL
  في سياق UNIQUE فتبقى الحسابات الفردية سليمة.

P2.2 — ON DELETE SET NULL:
  يُبدّل سلوك FK الحالي (NO ACTION) إلى SET NULL.
  عند حذف حساب موازٍ مباشرةً من DB يُصفَّر الإشارة إليه تلقائياً بدل
  رفع FK violation صامت. هذا safety net — الطريق الطبيعي للحذف يمر عبر
  remove_parallel_account() التي تُفسخ الربط يدوياً قبل الحذف.

Pre-migration audit (نُفِّذ يدوياً قبل هذا الـ migration):
  ✅ 0 duplicate_target
  ✅ 0 self_link
  ✅ 0 orphan_pointer
  ✅ 0 one_way_link
  ✅ 0 same_type_violations
  ✅ 1 tracks_weight_mismatch → صُحِّح (account 914, رقم 510)

Impact note: لا تغيير في بيانات الـ application، DDL فقط.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers
revision: str = '20260907_memo_account_pair_constraints'
down_revision: Union[str, Sequence[str], None] = (
    '20260519_goal_bonus_fields',
    'reservation_outbox_001',
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    # P2.1 — UNIQUE(memo_account_id)
    # يوجد partial index يدوي (WHERE IS NOT NULL) بنفس الاسم —
    # نُسقطه ونُنشئ UNIQUE constraint رسمياً بدلاً منه.
    # السلوك متطابق: PostgreSQL يعتبر NULL ≠ NULL في UNIQUE فتُسمح NULLs.
    op.drop_index('uq_account_memo_account_id', table_name='account')
    op.create_unique_constraint(
        'uq_account_memo_account_id', 'account', ['memo_account_id']
    )

    # P2.2 — استبدال FK (NO ACTION → SET NULL)
    op.drop_constraint(
        'account_memo_account_id_fkey', 'account', type_='foreignkey'
    )
    op.create_foreign_key(
        'account_memo_account_id_fkey',
        'account', 'account',
        ['memo_account_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    # استعادة FK الأصلي (NO ACTION)
    op.drop_constraint(
        'account_memo_account_id_fkey', 'account', type_='foreignkey'
    )
    op.create_foreign_key(
        'account_memo_account_id_fkey',
        'account', 'account',
        ['memo_account_id'], ['id'],
        ondelete='NO ACTION',
    )
    # استعادة الـ partial index بدل الـ UNIQUE constraint
    op.drop_constraint('uq_account_memo_account_id', 'account', type_='unique')
    op.execute(
        'CREATE UNIQUE INDEX uq_account_memo_account_id '
        'ON account (memo_account_id) '
        'WHERE memo_account_id IS NOT NULL'
    )
