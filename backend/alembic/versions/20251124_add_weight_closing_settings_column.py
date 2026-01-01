"""add weight closing settings column

Revision ID: 20251124_add_weight_closing_settings
Revises: 20251124_weight_closing
Create Date: 2025-11-24 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '20251124_add_weight_closing_settings'
down_revision: Union[str, Sequence[str], None] = '20251124_weight_closing'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    settings_columns = {col['name'] for col in inspector.get_columns('settings')}
    if 'weight_closing_settings' not in settings_columns:
        with op.batch_alter_table('settings', schema=None) as batch_op:
            batch_op.add_column(sa.Column('weight_closing_settings', sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    settings_columns = {col['name'] for col in inspector.get_columns('settings')}
    if 'weight_closing_settings' in settings_columns:
        with op.batch_alter_table('settings', schema=None) as batch_op:
            batch_op.drop_column('weight_closing_settings')
