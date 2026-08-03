"""Phase 4 Bonus: feature flags للـ attendance و performance في Settings

Revision ID: bonus_phase4_feature_flags_001
Revises: bonus_phase3_snapshots_001
Create Date: 2026-08-03

Impact:
  - ADD COLUMN settings.bonus_attendance_enabled  BOOLEAN  DEFAULT false
  - ADD COLUMN settings.bonus_performance_enabled BOOLEAN  DEFAULT false

Destructive: NO — nullable + server_default false.
السبب: attendance وperformance يعتمدان على placeholders حالياً؛
       يُمنع إنشاؤهما في الإنتاج حتى يُفعَّلا صراحةً من الإعدادات.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'bonus_phase4_feature_flags_001'
down_revision: Union[str, Sequence[str], None] = 'bonus_phase3_snapshots_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('settings',
        sa.Column('bonus_attendance_enabled', sa.Boolean,
                  nullable=False, server_default=sa.false()))
    op.add_column('settings',
        sa.Column('bonus_performance_enabled', sa.Boolean,
                  nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('settings', 'bonus_performance_enabled')
    op.drop_column('settings', 'bonus_attendance_enabled')
