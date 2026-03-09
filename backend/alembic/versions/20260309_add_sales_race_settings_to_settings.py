"""add sales_race_settings to settings

Revision ID: 20260309_sales_race
Revises: 92f5e99c571a
Create Date: 2026-03-09 11:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '20260309_sales_race'
down_revision: Union[str, Sequence[str], None] = '92f5e99c571a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    settings_columns = {col['name'] for col in inspector.get_columns('settings')}
    if 'sales_race_settings' not in settings_columns:
        with op.batch_alter_table('settings', schema=None) as batch_op:
            batch_op.add_column(sa.Column('sales_race_settings', sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    settings_columns = {col['name'] for col in inspector.get_columns('settings')}
    if 'sales_race_settings' in settings_columns:
        with op.batch_alter_table('settings', schema=None) as batch_op:
            batch_op.drop_column('sales_race_settings')
