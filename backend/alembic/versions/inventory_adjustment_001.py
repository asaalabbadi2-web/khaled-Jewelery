"""Add inventory_adjustment and inventory_adjustment_line tables (Phase 4)

Revision ID: inventory_adjustment_001
Revises: inventory_count_001
Create Date: 2026-07-05

"""
from alembic import op
import sqlalchemy as sa

revision = 'inventory_adjustment_001'
down_revision = 'inventory_count_001'
branch_labels = None
depends_on = None


def upgrade():
    # ── InventoryAdjustment ───────────────────────────────────────────────────
    op.create_table(
        'inventory_adjustment',
        sa.Column('id',              sa.Integer(),    primary_key=True),
        sa.Column('session_id',      sa.Integer(),
                  sa.ForeignKey('inventory_count_session.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('branch_id',       sa.Integer(),    sa.ForeignKey('branch.id'), nullable=True),
        sa.Column('adjustment_type', sa.String(30),   nullable=False, server_default='manual'),
        sa.Column('status',          sa.String(20),   nullable=False, server_default='draft'),
        sa.Column('reason',          sa.String(200),  nullable=True),
        sa.Column('created_by',      sa.String(100),  nullable=True),
        sa.Column('created_at',      sa.DateTime(),   nullable=False),
        sa.Column('posted_by',       sa.String(100),  nullable=True),
        sa.Column('posted_at',       sa.DateTime(),   nullable=True),
        sa.Column('gl_entry_id',     sa.Integer(),    nullable=True),
        sa.Column('notes',           sa.Text(),       nullable=True),
    )
    op.create_index('ix_inventory_adjustment_session_id', 'inventory_adjustment', ['session_id'])
    op.create_index('ix_inventory_adjustment_branch_id',  'inventory_adjustment', ['branch_id'])
    op.create_index('ix_inventory_adjustment_status',     'inventory_adjustment', ['status'])

    # ── InventoryAdjustmentLine ───────────────────────────────────────────────
    op.create_table(
        'inventory_adjustment_line',
        sa.Column('id',               sa.Integer(), primary_key=True),
        sa.Column('adjustment_id',    sa.Integer(),
                  sa.ForeignKey('inventory_adjustment.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('branch_id',        sa.Integer(), sa.ForeignKey('branch.id'),   nullable=True),
        sa.Column('category_id',      sa.Integer(), sa.ForeignKey('category.id'), nullable=True),
        sa.Column('karat',            sa.Float(),   nullable=False),
        sa.Column('expected_weight',  sa.Float(),   nullable=False, server_default='0'),
        sa.Column('counted_weight',   sa.Float(),   nullable=False, server_default='0'),
        sa.Column('variance_weight',  sa.Float(),   nullable=False),
        sa.Column('notes',            sa.Text(),    nullable=True),
    )
    op.create_index('ix_inventory_adjustment_line_adj_id', 'inventory_adjustment_line', ['adjustment_id'])
    op.create_unique_constraint(
        'uq_inventory_adjustment_line_bucket',
        'inventory_adjustment_line',
        ['adjustment_id', 'category_id', 'karat'],
    )


def downgrade():
    op.drop_table('inventory_adjustment_line')
    op.drop_table('inventory_adjustment')
