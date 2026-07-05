"""Add inventory_balance table (Phase 2 — Balance Projection)

Revision ID: inventory_balance_001
Revises: inventory_ledger_001
Create Date: 2026-07-05

"""
from alembic import op
import sqlalchemy as sa

revision = 'inventory_balance_001'
down_revision = 'inventory_ledger_001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'inventory_balance',
        sa.Column('id',                     sa.Integer(),   primary_key=True),
        sa.Column('branch_id',              sa.Integer(),   sa.ForeignKey('branch.id'),   nullable=True),
        sa.Column('category_id',            sa.Integer(),   sa.ForeignKey('category.id'), nullable=True),
        sa.Column('karat',                  sa.Float(),     nullable=False),
        sa.Column('balance',                sa.Float(),     nullable=False, server_default='0'),
        sa.Column('snapshot_max_ledger_id', sa.Integer(),   nullable=True),
        sa.Column('updated_at',             sa.DateTime(),  nullable=False),
    )

    op.create_unique_constraint(
        'uq_inventory_balance_bucket',
        'inventory_balance',
        ['branch_id', 'category_id', 'karat'],
    )

    op.create_index(
        'ix_inventory_balance_bucket',
        'inventory_balance',
        ['branch_id', 'category_id', 'karat'],
    )


def downgrade():
    op.drop_table('inventory_balance')
