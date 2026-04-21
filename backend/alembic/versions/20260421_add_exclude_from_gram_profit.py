"""add exclude_from_gram_profit and monthly_sales_target_weight

Revision ID: 20260421_exclude_gram_profit
Revises: 20260417_settlement_line
Create Date: 2026-04-21
"""
from alembic import op
import sqlalchemy as sa

revision = '20260421_exclude_gram_profit'
down_revision = '20260417_settlement_line'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('account') as batch_op:
        batch_op.add_column(
            sa.Column(
                'exclude_from_gram_profit',
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
    with op.batch_alter_table('settings') as batch_op:
        batch_op.add_column(
            sa.Column(
                'monthly_sales_target_weight',
                sa.Float(),
                nullable=True,
                server_default='8000.0',
            )
        )


def downgrade():
    with op.batch_alter_table('account') as batch_op:
        batch_op.drop_column('exclude_from_gram_profit')
    with op.batch_alter_table('settings') as batch_op:
        batch_op.drop_column('monthly_sales_target_weight')
