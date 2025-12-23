"""add_stones_fields_to_items

Revision ID: c745c5513330
Revises: c78d19e04615
Create Date: 2025-11-15 18:19:45.148795

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'c745c5513330'
down_revision: Union[str, Sequence[str], None] = 'c78d19e04615'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_columns = {col['name'] for col in inspector.get_columns('item')}

    with op.batch_alter_table('item', schema=None) as batch_op:
        if 'has_stones' not in existing_columns:
            batch_op.add_column(sa.Column('has_stones', sa.Boolean(), nullable=False, server_default='0'))
        if 'stones_weight' not in existing_columns:
            batch_op.add_column(sa.Column('stones_weight', sa.Float(), nullable=True))
        if 'stones_value' not in existing_columns:
            batch_op.add_column(sa.Column('stones_value', sa.Float(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_columns = {col['name'] for col in inspector.get_columns('item')}

    with op.batch_alter_table('item', schema=None) as batch_op:
        if 'stones_value' in existing_columns:
            batch_op.drop_column('stones_value')
        if 'stones_weight' in existing_columns:
            batch_op.drop_column('stones_weight')
        if 'has_stones' in existing_columns:
            batch_op.drop_column('has_stones')
