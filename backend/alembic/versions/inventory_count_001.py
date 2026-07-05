"""Add inventory_count_session and inventory_count_line tables (Phase 3)

Revision ID: inventory_count_001
Revises: inventory_balance_001
Create Date: 2026-07-05

"""
from alembic import op
import sqlalchemy as sa

revision = 'inventory_count_001'
down_revision = 'inventory_balance_001'
branch_labels = None
depends_on = None


def upgrade():
    # ── InventoryCountSession ─────────────────────────────────────────────────
    op.create_table(
        'inventory_count_session',
        sa.Column('id',                 sa.Integer(),   primary_key=True),
        sa.Column('branch_id',          sa.Integer(),   sa.ForeignKey('branch.id'),  nullable=True),
        sa.Column('status',             sa.String(20),  nullable=False, server_default='open'),
        sa.Column('snapshot_ledger_id', sa.Integer(),   nullable=True),
        sa.Column('opened_by',          sa.String(100), nullable=True),
        sa.Column('opened_at',          sa.DateTime(),  nullable=False),
        sa.Column('closed_at',          sa.DateTime(),  nullable=True),
        sa.Column('approved_by',        sa.String(100), nullable=True),
        sa.Column('approved_at',        sa.DateTime(),  nullable=True),
        sa.Column('notes',              sa.Text(),      nullable=True),
    )
    op.create_index('ix_inventory_count_session_branch_id', 'inventory_count_session', ['branch_id'])
    op.create_index('ix_inventory_count_session_status',    'inventory_count_session', ['status'])

    # ── InventoryCountLine ────────────────────────────────────────────────────
    op.create_table(
        'inventory_count_line',
        sa.Column('id',                 sa.Integer(),   primary_key=True),
        sa.Column('session_id',         sa.Integer(),
                  sa.ForeignKey('inventory_count_session.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('branch_id',          sa.Integer(),   sa.ForeignKey('branch.id'),   nullable=True),
        sa.Column('category_id',        sa.Integer(),   sa.ForeignKey('category.id'), nullable=True),
        sa.Column('karat',              sa.Float(),     nullable=False),
        sa.Column('expected_weight',    sa.Float(),     nullable=False, server_default='0'),
        sa.Column('expected_ledger_id', sa.Integer(),   nullable=True),
        sa.Column('counted_weight',     sa.Float(),     nullable=True),
        sa.Column('variance',           sa.Float(),     nullable=True),
        sa.Column('counted_by',         sa.String(100), nullable=True),
        sa.Column('counted_at',         sa.DateTime(),  nullable=True),
        sa.Column('notes',              sa.Text(),      nullable=True),
    )
    op.create_index('ix_inventory_count_line_session_id', 'inventory_count_line', ['session_id'])
    op.create_unique_constraint(
        'uq_inventory_count_line_bucket',
        'inventory_count_line',
        ['session_id', 'category_id', 'karat'],
    )


def downgrade():
    op.drop_table('inventory_count_line')
    op.drop_table('inventory_count_session')
