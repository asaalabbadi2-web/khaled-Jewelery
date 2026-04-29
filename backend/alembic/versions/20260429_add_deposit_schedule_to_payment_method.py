"""add deposit_schedule_type, deposit_weekday, deposit_delay_days to payment_method

Revision ID: 20260429_deposit_schedule_pm
Revises: 20260305_settlement_mode_pm
Create Date: 2026-04-29 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260429_deposit_schedule_pm'
down_revision: Union[str, None] = '20260305_settlement_mode_pm'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c['name'] for c in inspector.get_columns('payment_method')}

    with op.batch_alter_table('payment_method', schema=None) as batch_op:
        if 'deposit_delay_days' not in existing:
            batch_op.add_column(
                sa.Column('deposit_delay_days', sa.Integer(), nullable=False, server_default='0')
            )
        if 'deposit_schedule_type' not in existing:
            batch_op.add_column(
                sa.Column('deposit_schedule_type', sa.String(length=20), nullable=False, server_default='days')
            )
        if 'deposit_weekday' not in existing:
            batch_op.add_column(
                sa.Column('deposit_weekday', sa.Integer(), nullable=True)
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c['name'] for c in inspector.get_columns('payment_method')}

    with op.batch_alter_table('payment_method', schema=None) as batch_op:
        if 'deposit_weekday' in existing:
            batch_op.drop_column('deposit_weekday')
        if 'deposit_schedule_type' in existing:
            batch_op.drop_column('deposit_schedule_type')
        if 'deposit_delay_days' in existing:
            batch_op.drop_column('deposit_delay_days')
