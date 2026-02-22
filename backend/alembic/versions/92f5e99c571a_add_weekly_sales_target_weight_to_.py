"""add weekly_sales_target_weight to settings

Revision ID: 92f5e99c571a
Revises: db170a4761ae
Create Date: 2026-02-22 07:31:58.048881

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '92f5e99c571a'
down_revision: Union[str, Sequence[str], None] = 'db170a4761ae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = inspect(bind)

    settings_columns = {col['name'] for col in inspector.get_columns('settings')}
    if 'weekly_sales_target_weight' not in settings_columns:
        with op.batch_alter_table('settings', schema=None) as batch_op:
            batch_op.add_column(sa.Column('weekly_sales_target_weight', sa.Float(), nullable=True))

    # Ensure existing rows get a sensible default.
    op.execute(
        sa.text(
            "UPDATE settings SET weekly_sales_target_weight = 2000.0 "
            "WHERE weekly_sales_target_weight IS NULL"
        )
    )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = inspect(bind)

    settings_columns = {col['name'] for col in inspector.get_columns('settings')}
    if 'weekly_sales_target_weight' in settings_columns:
        with op.batch_alter_table('settings', schema=None) as batch_op:
            batch_op.drop_column('weekly_sales_target_weight')
