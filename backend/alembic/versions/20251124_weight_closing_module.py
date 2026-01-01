"""add weight closing module

Revision ID: 20251124_weight_closing
Revises: 20251121_gold_costing
Create Date: 2025-11-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, func


# revision identifiers, used by Alembic.
revision: str = '20251124_weight_closing'
down_revision: Union[str, Sequence[str], None] = '20251121_gold_costing'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    invoice_item_columns = {col['name'] for col in inspector.get_columns('invoice_item')}
    with op.batch_alter_table('invoice_item', schema=None) as batch_op:
        if 'avg_cost_per_gram_snapshot' not in invoice_item_columns:
            batch_op.add_column(sa.Column('avg_cost_per_gram_snapshot', sa.Float(), nullable=False, server_default='0'))
        if 'profit_cash' not in invoice_item_columns:
            batch_op.add_column(sa.Column('profit_cash', sa.Float(), nullable=False, server_default='0'))
        if 'profit_weight' not in invoice_item_columns:
            batch_op.add_column(sa.Column('profit_weight', sa.Float(), nullable=False, server_default='0'))
        if 'profit_weight_price_per_gram' not in invoice_item_columns:
            batch_op.add_column(sa.Column('profit_weight_price_per_gram', sa.Float(), nullable=False, server_default='0'))

    invoice_columns = {col['name'] for col in inspector.get_columns('invoice')}
    with op.batch_alter_table('invoice', schema=None) as batch_op:
        if 'profit_weight_price_per_gram' not in invoice_columns:
            batch_op.add_column(sa.Column('profit_weight_price_per_gram', sa.Float(), nullable=False, server_default='0'))

    if not inspector.has_table('weight_closing_log'):
        op.create_table(
            'weight_closing_log',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('sale_item_id', sa.Integer(), sa.ForeignKey('invoice_item.id'), nullable=False),
            sa.Column('profit_weight', sa.Float(), nullable=False, server_default='0'),
            sa.Column('profit_cash', sa.Float(), nullable=False, server_default='0'),
            sa.Column('snapshot_cost_per_gram', sa.Float(), nullable=False, server_default='0'),
            sa.Column('close_price', sa.Float(), nullable=False),
            sa.Column('close_value', sa.Float(), nullable=False, server_default='0'),
            sa.Column('difference_value', sa.Float(), nullable=False, server_default='0'),
            sa.Column('difference_weight', sa.Float(), nullable=False, server_default='0'),
            sa.Column('close_date', sa.DateTime(), nullable=False, server_default=func.now()),
            sa.Column('journal_entry_id', sa.Integer(), sa.ForeignKey('journal_entry.id'), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_weight_closing_log_sale_item_id', 'weight_closing_log', ['sale_item_id'], unique=False)
    else:
        existing_columns = {col['name'] for col in inspector.get_columns('weight_closing_log')}
        with op.batch_alter_table('weight_closing_log', schema=None) as batch_op:
            if 'journal_entry_id' not in existing_columns:
                batch_op.add_column(sa.Column('journal_entry_id', sa.Integer(), sa.ForeignKey('journal_entry.id'), nullable=True))
        existing_indexes = {idx['name'] for idx in inspector.get_indexes('weight_closing_log')}
        if 'ix_weight_closing_log_sale_item_id' not in existing_indexes:
            op.create_index('ix_weight_closing_log_sale_item_id', 'weight_closing_log', ['sale_item_id'], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table('weight_closing_log'):
        op.drop_index('ix_weight_closing_log_sale_item_id', table_name='weight_closing_log')
        op.drop_table('weight_closing_log')

    invoice_item_columns = {col['name'] for col in inspector.get_columns('invoice_item')}
    with op.batch_alter_table('invoice_item', schema=None) as batch_op:
        if 'profit_weight_price_per_gram' in invoice_item_columns:
            batch_op.drop_column('profit_weight_price_per_gram')
        if 'profit_weight' in invoice_item_columns:
            batch_op.drop_column('profit_weight')
        if 'profit_cash' in invoice_item_columns:
            batch_op.drop_column('profit_cash')
        if 'avg_cost_per_gram_snapshot' in invoice_item_columns:
            batch_op.drop_column('avg_cost_per_gram_snapshot')

    invoice_columns = {col['name'] for col in inspector.get_columns('invoice')}
    with op.batch_alter_table('invoice', schema=None) as batch_op:
        if 'profit_weight_price_per_gram' in invoice_columns:
            batch_op.drop_column('profit_weight_price_per_gram')
