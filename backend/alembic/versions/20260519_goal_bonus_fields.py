"""add goal_bonus_monthly and goal_bonus_weekly to employee

Revision ID: 20260519_goal_bonus_fields
Revises: 20260421_exclude_gram_profit, 20260429_deposit_schedule_pm, expand_currency_symbol_001
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '20260519_goal_bonus_fields'
down_revision = (
    '20260421_exclude_gram_profit',
    '20260429_deposit_schedule_pm',
    'expand_currency_symbol_001',
)
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('employee') as batch_op:
        batch_op.add_column(
            sa.Column('goal_bonus_monthly', sa.Float(), nullable=True)
        )
        batch_op.add_column(
            sa.Column('goal_bonus_weekly', sa.Float(), nullable=True)
        )


def downgrade():
    with op.batch_alter_table('employee') as batch_op:
        batch_op.drop_column('goal_bonus_weekly')
        batch_op.drop_column('goal_bonus_monthly')
