"""Phase 7 Bonus: جدول سجل تشغيلات المجدول (BonusCalculationLog)

Revision ID: bonus_phase7_scheduler_log_001
Revises: bonus_phase5_points_source_001
Create Date: 2026-08-03

Impact:
  - CREATE TABLE bonus_calculation_log
    سجل قابل للقراءة من الواجهة يُظهر آخر تشغيلات المجدول
    مع عدد المكافآت التي أُنشئت وإجمالي المبلغ.

Destructive: NO — جدول جديد لا يؤثر على أي بيانات قائمة.
ملاحظة: لا يرتبط بـ bonus_phase6 لأن Phase 6 لم تُنشئ migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'bonus_phase7_scheduler_log_001'
down_revision: Union[str, Sequence[str], None] = 'bonus_phase5_points_source_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'bonus_calculation_log',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('run_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column('period_type', sa.String(20), nullable=False),   # daily | weekly | monthly | manual
        sa.Column('period_start', sa.Date, nullable=False),
        sa.Column('period_end', sa.Date, nullable=False),
        sa.Column('bonus_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('total_amount', sa.Float, nullable=False, server_default='0'),
        sa.Column('status', sa.String(20), nullable=False, server_default='success'),  # success | failed
        sa.Column('message', sa.Text, nullable=True),
    )
    op.create_index('ix_bonus_calculation_log_run_at', 'bonus_calculation_log', ['run_at'])
    op.create_index('ix_bonus_calculation_log_period', 'bonus_calculation_log',
                    ['period_start', 'period_end'])


def downgrade() -> None:
    op.drop_index('ix_bonus_calculation_log_period', table_name='bonus_calculation_log')
    op.drop_index('ix_bonus_calculation_log_run_at', table_name='bonus_calculation_log')
    op.drop_table('bonus_calculation_log')
