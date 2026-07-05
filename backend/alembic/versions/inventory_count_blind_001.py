"""Add blind_count column to inventory_count_session

Revision ID: inventory_count_blind_001
Revises: inventory_adjustment_001
Create Date: 2026-07-05

Adds blind_count (Boolean, default True) to inventory_count_session.
When True, expected_weight is hidden from the API response while the
session is open/counting — prevents anchoring bias and manipulation.
"""
from alembic import op
import sqlalchemy as sa

revision = 'inventory_count_blind_001'
down_revision = 'inventory_adjustment_001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('inventory_count_session') as batch_op:
        batch_op.add_column(
            sa.Column('blind_count', sa.Boolean(), nullable=False,
                      server_default=sa.text('1'))  # SQLite: 1=True
        )


def downgrade():
    with op.batch_alter_table('inventory_count_session') as batch_op:
        batch_op.drop_column('blind_count')
