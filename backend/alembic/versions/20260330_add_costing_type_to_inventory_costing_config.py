"""Add costing_type column to inventory_costing_config

Revision ID: 20260330_costing_type_001
Revises: 20260319_add_company_cr_number_to_settings
Create Date: 2026-03-30

Adds a 'costing_type' discriminator column so we can maintain separate
moving-average accumulators for:
  - 'normal' : regular supplier purchases (new gold)
  - 'scrap'  : scrap buybacks from customers + office settlements

Existing rows are back-filled with 'normal'.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260330_costing_type_001'
down_revision = '20260319_add_company_cr_number_to_settings'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()

    # 1. Add the new column (nullable first so existing rows are OK)
    try:
        op.add_column(
            'inventory_costing_config',
            sa.Column('costing_type', sa.String(20), nullable=True, server_default='normal'),
        )
    except Exception:
        # Column may already exist (re-run safety)
        pass

    # 2. Back-fill existing rows → 'normal'
    connection.execute(
        sa.text(
            "UPDATE inventory_costing_config SET costing_type = 'normal' "
            "WHERE costing_type IS NULL"
        )
    )


def downgrade():
    try:
        op.drop_column('inventory_costing_config', 'costing_type')
    except Exception:
        pass
