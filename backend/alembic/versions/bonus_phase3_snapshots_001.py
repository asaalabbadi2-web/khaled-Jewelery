"""Phase 3 Bonus: rule_snapshot + calculation_snapshot on employee_bonus

Revision ID: bonus_phase3_snapshots_001
Revises: bonus_phase2_reversal_001
Create Date: 2026-08-03

Impact:
  - ADD COLUMN employee_bonus.rule_snapshot        JSON  NULL
  - ADD COLUMN employee_bonus.calculation_snapshot JSON  NULL

Destructive: NO — nullable columns, no data migration needed.
Write-once: application layer enforces no update on existing bonuses
            (see BonusCalculator.calculate_all_bonuses_for_period).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'bonus_phase3_snapshots_001'
down_revision: Union[str, Sequence[str], None] = 'bonus_phase2_reversal_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('employee_bonus',
        sa.Column('rule_snapshot', sa.JSON, nullable=True))
    op.add_column('employee_bonus',
        sa.Column('calculation_snapshot', sa.JSON, nullable=True))


def downgrade() -> None:
    op.drop_column('employee_bonus', 'calculation_snapshot')
    op.drop_column('employee_bonus', 'rule_snapshot')
