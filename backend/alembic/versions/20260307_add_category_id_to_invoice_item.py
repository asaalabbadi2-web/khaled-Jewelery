"""add category_id to invoice_item

Revision ID: 20260307_add_category_id_to_invoice_item
Revises:
Create Date: 2026-03-07
"""
from alembic import op
import sqlalchemy as sa

revision = '20260307_add_category_id_to_invoice_item'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('invoice_item', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('category_id', sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            'fk_invoice_item_category_id',
            'category',
            ['category_id'],
            ['id'],
        )


def downgrade():
    with op.batch_alter_table('invoice_item', schema=None) as batch_op:
        batch_op.drop_constraint('fk_invoice_item_category_id', type_='foreignkey')
        batch_op.drop_column('category_id')
