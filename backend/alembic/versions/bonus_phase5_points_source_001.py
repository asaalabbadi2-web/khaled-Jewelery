"""Phase 5 Bonus: points_source على BonusRule لتحديد مصدر نقاط points_based

Revision ID: bonus_phase5_points_source_001
Revises: bonus_phase4_feature_flags_001
Create Date: 2026-08-03

Impact:
  - ADD COLUMN bonus_rule.points_source  VARCHAR(10)  DEFAULT NULL  NULLABLE
  - ADD CHECK   ck_bonus_rule_points_source: points_source IN ('gold', 'cash')

Destructive: NO — nullable, قواعد points_based الحالية تبقى تعمل بمسار gold (الافتراضي).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'bonus_phase5_points_source_001'
down_revision: Union[str, Sequence[str], None] = 'bonus_phase4_feature_flags_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('bonus_rule',
        sa.Column('points_source', sa.String(10), nullable=True))
    op.create_check_constraint(
        'ck_bonus_rule_points_source',
        'bonus_rule',
        "points_source IN ('gold', 'cash')",
    )


def downgrade() -> None:
    op.drop_constraint('ck_bonus_rule_points_source', 'bonus_rule', type_='check')
    op.drop_column('bonus_rule', 'points_source')
