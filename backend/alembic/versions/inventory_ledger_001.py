"""Add inventory_ledger table (Phase 1 — Event Log)

Revision ID: inventory_ledger_001
Revises: weight_type_field_001
Create Date: 2026-07-05

"""
from alembic import op
import sqlalchemy as sa

revision = 'inventory_ledger_001'
down_revision = 'weight_type_field_001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'inventory_ledger',
        sa.Column('id',             sa.Integer(),     primary_key=True),
        sa.Column('source_type',    sa.String(40),    nullable=False),
        sa.Column('source_id',      sa.Integer(),     nullable=False),
        sa.Column('source_line_id', sa.Integer(),     nullable=True),
        sa.Column('movement_type',  sa.String(30),    nullable=False),
        sa.Column('branch_id',      sa.Integer(),     sa.ForeignKey('branch.id'),   nullable=True),
        sa.Column('category_id',    sa.Integer(),     sa.ForeignKey('category.id'), nullable=True),
        sa.Column('karat',          sa.Float(),       nullable=False),
        sa.Column('weight_delta',   sa.Float(),       nullable=False),
        sa.Column('posted_at',      sa.DateTime(),    nullable=False),
        sa.Column('posted_by',      sa.String(100),   nullable=True),
        sa.Column('notes',          sa.Text(),        nullable=True),
    )

    # Idempotency: one entry per (source_line × movement_type)
    op.create_unique_constraint(
        'uq_inventory_ledger_idempotency',
        'inventory_ledger',
        ['source_type', 'source_id', 'source_line_id', 'movement_type'],
    )

    # Query indexes
    op.create_index('ix_inventory_ledger_source_type',   'inventory_ledger', ['source_type'])
    op.create_index('ix_inventory_ledger_source_id',     'inventory_ledger', ['source_id'])
    op.create_index('ix_inventory_ledger_movement_type', 'inventory_ledger', ['movement_type'])
    op.create_index('ix_inventory_ledger_branch_id',     'inventory_ledger', ['branch_id'])
    op.create_index('ix_inventory_ledger_category_id',   'inventory_ledger', ['category_id'])
    op.create_index('ix_inventory_ledger_posted_at',     'inventory_ledger', ['posted_at'])
    op.create_index(
        'ix_inventory_ledger_bucket',
        'inventory_ledger',
        ['branch_id', 'category_id', 'karat'],
    )


def downgrade():
    op.drop_table('inventory_ledger')
