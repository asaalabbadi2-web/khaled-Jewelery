"""add category_id to invoice_item

Revision ID: 20260307_add_category_id_to_invoice_item
Revises:
Create Date: 2026-03-07
"""
from alembic import op
from alembic import context
import sqlalchemy as sa

revision = '20260307_add_category_id_to_invoice_item'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Idempotent migration: some production DBs may already have the column.
    # In offline mode we can't introspect, so emit the original operations.
    if context.is_offline_mode():
        with op.batch_alter_table('invoice_item', schema=None) as batch_op:
            batch_op.add_column(sa.Column('category_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                'fk_invoice_item_category_id',
                'category',
                ['category_id'],
                ['id'],
            )
        return

    conn = op.get_bind()
    inspector = sa.inspect(conn)

    columns = {c['name'] for c in inspector.get_columns('invoice_item')}
    has_category_id = 'category_id' in columns

    foreign_keys = inspector.get_foreign_keys('invoice_item')
    has_fk = any(
        (fk.get('referred_table') == 'category')
        and (fk.get('constrained_columns') == ['category_id'])
        for fk in foreign_keys
    )

    with op.batch_alter_table('invoice_item', schema=None) as batch_op:
        if not has_category_id:
            batch_op.add_column(sa.Column('category_id', sa.Integer(), nullable=True))
        if not has_fk:
            batch_op.create_foreign_key(
                'fk_invoice_item_category_id',
                'category',
                ['category_id'],
                ['id'],
            )


def downgrade():
    if context.is_offline_mode():
        with op.batch_alter_table('invoice_item', schema=None) as batch_op:
            batch_op.drop_constraint('fk_invoice_item_category_id', type_='foreignkey')
            batch_op.drop_column('category_id')
        return

    conn = op.get_bind()
    inspector = sa.inspect(conn)

    columns = {c['name'] for c in inspector.get_columns('invoice_item')}
    if 'category_id' not in columns:
        return

    fk_name = None
    for fk in inspector.get_foreign_keys('invoice_item'):
        if (fk.get('referred_table') == 'category') and (fk.get('constrained_columns') == ['category_id']):
            fk_name = fk.get('name')
            break

    with op.batch_alter_table('invoice_item', schema=None) as batch_op:
        if fk_name:
            batch_op.drop_constraint(fk_name, type_='foreignkey')
        batch_op.drop_column('category_id')
