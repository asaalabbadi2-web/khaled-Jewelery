"""add gold costing schema

Revision ID: 20251121_gold_costing
Revises: c78d19e04615
Create Date: 2025-11-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.sql import func


# revision identifiers, used by Alembic.
revision: str = '20251121_gold_costing'
down_revision: Union[str, Sequence[str], None] = 'c78d19e04615'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    insert_default_config = False

    if not inspector.has_table('inventory_costing_config'):
        op.create_table(
            'inventory_costing_config',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('costing_method', sa.String(length=20), nullable=False, server_default='moving_average'),
            sa.Column('current_avg_cost_per_gram', sa.Float(), nullable=False, server_default='0'),
            sa.Column('avg_gold_price_per_gram', sa.Float(), nullable=False, server_default='0'),
            sa.Column('avg_manufacturing_per_gram', sa.Float(), nullable=False, server_default='0'),
            sa.Column('avg_total_cost_per_gram', sa.Float(), nullable=False, server_default='0'),
            sa.Column('total_inventory_weight', sa.Float(), nullable=False, server_default='0'),
            sa.Column('total_gold_value', sa.Float(), nullable=False, server_default='0'),
            sa.Column('total_manufacturing_value', sa.Float(), nullable=False, server_default='0'),
            sa.Column('last_purchase_price', sa.Float(), nullable=True),
            sa.Column('last_purchase_weight', sa.Float(), nullable=True),
            sa.Column('last_updated', sa.DateTime(), nullable=True, server_default=func.now()),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=func.now()),
            sa.PrimaryKeyConstraint('id')
        )
        insert_default_config = True

    if not inspector.has_table('supplier_gold_transaction'):
        op.create_table(
            'supplier_gold_transaction',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('supplier_id', sa.Integer(), sa.ForeignKey('supplier.id'), nullable=False),
            sa.Column('invoice_id', sa.Integer(), sa.ForeignKey('invoice.id'), nullable=True),
            sa.Column('journal_entry_id', sa.Integer(), sa.ForeignKey('journal_entry.id'), nullable=True),
            sa.Column('transaction_type', sa.String(length=50), nullable=False),
            sa.Column('gold_weight', sa.Float(), nullable=False),
            sa.Column('original_karat', sa.Float(), nullable=True),
            sa.Column('original_weight', sa.Float(), nullable=True),
            sa.Column('price_per_gram', sa.Float(), nullable=False),
            sa.Column('manufacturing_wage_per_gram', sa.Float(), nullable=False, server_default='0'),
            sa.Column('cash_amount', sa.Float(), nullable=False),
            sa.Column('settlement_price_per_gram', sa.Float(), nullable=True),
            sa.Column('settlement_cash_amount', sa.Float(), nullable=False, server_default='0'),
            sa.Column('settlement_gold_weight', sa.Float(), nullable=False, server_default='0'),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('transaction_date', sa.DateTime(), nullable=False, server_default=func.now()),
            sa.Column('created_by', sa.String(length=100), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=func.now()),
            sa.PrimaryKeyConstraint('id')
        )

    supplier_columns = {col['name'] for col in inspector.get_columns('supplier')}
    with op.batch_alter_table('supplier', schema=None) as batch_op:
        if 'gold_balance_weight' not in supplier_columns:
            batch_op.add_column(sa.Column('gold_balance_weight', sa.Float(), nullable=False, server_default='0'))
        if 'gold_balance_cash_equivalent' not in supplier_columns:
            batch_op.add_column(sa.Column('gold_balance_cash_equivalent', sa.Float(), nullable=False, server_default='0'))
        if 'last_gold_transaction_date' not in supplier_columns:
            batch_op.add_column(sa.Column('last_gold_transaction_date', sa.DateTime(), nullable=True))

    invoice_columns = {col['name'] for col in inspector.get_columns('invoice')}
    with op.batch_alter_table('invoice', schema=None) as batch_op:
        if 'avg_cost_per_gram_snapshot' not in invoice_columns:
            batch_op.add_column(sa.Column('avg_cost_per_gram_snapshot', sa.Float(), nullable=False, server_default='0'))
        if 'avg_cost_gold_component' not in invoice_columns:
            batch_op.add_column(sa.Column('avg_cost_gold_component', sa.Float(), nullable=False, server_default='0'))
        if 'avg_cost_manufacturing_component' not in invoice_columns:
            batch_op.add_column(sa.Column('avg_cost_manufacturing_component', sa.Float(), nullable=False, server_default='0'))
        if 'avg_cost_total_snapshot' not in invoice_columns:
            batch_op.add_column(sa.Column('avg_cost_total_snapshot', sa.Float(), nullable=False, server_default='0'))
        if 'settlement_status' not in invoice_columns:
            batch_op.add_column(sa.Column('settlement_status', sa.String(length=20), nullable=False, server_default='pending'))
        if 'settlement_method' not in invoice_columns:
            batch_op.add_column(sa.Column('settlement_method', sa.String(length=20), nullable=True))
        if 'settlement_date' not in invoice_columns:
            batch_op.add_column(sa.Column('settlement_date', sa.DateTime(), nullable=True))
        if 'settlement_price_per_gram' not in invoice_columns:
            batch_op.add_column(sa.Column('settlement_price_per_gram', sa.Float(), nullable=True))
        if 'settlement_cash_amount' not in invoice_columns:
            batch_op.add_column(sa.Column('settlement_cash_amount', sa.Float(), nullable=False, server_default='0'))
        if 'settlement_gold_weight' not in invoice_columns:
            batch_op.add_column(sa.Column('settlement_gold_weight', sa.Float(), nullable=False, server_default='0'))

    jel_columns = {col['name'] for col in inspector.get_columns('journal_entry_line')}
    with op.batch_alter_table('journal_entry_line', schema=None) as batch_op:
        if 'gold_transaction_id' not in jel_columns:
            batch_op.add_column(sa.Column('gold_transaction_id', sa.Integer(), nullable=True))
        if 'gold_weight_equiv' not in jel_columns:
            batch_op.add_column(sa.Column('gold_weight_equiv', sa.Float(), nullable=True))
        if 'gold_price_applied' not in jel_columns:
            batch_op.add_column(sa.Column('gold_price_applied', sa.Float(), nullable=True))
        existing_constraints = {c['name'] for c in inspector.get_foreign_keys('journal_entry_line')}
        if 'fk_jel_gold_transaction' not in existing_constraints:
            batch_op.create_foreign_key(
                'fk_jel_gold_transaction',
                'supplier_gold_transaction',
                ['gold_transaction_id'],
                ['id']
            )

    if insert_default_config:
        op.execute(
            sa.text(
                "INSERT INTO inventory_costing_config "
                "(id, costing_method, current_avg_cost_per_gram, avg_gold_price_per_gram, avg_manufacturing_per_gram, avg_total_cost_per_gram, total_inventory_weight, total_gold_value, total_manufacturing_value, created_at, last_updated) "
                "VALUES (1, 'moving_average', 0, 0, 0, 0, 0, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )


def downgrade() -> None:
    with op.batch_alter_table('journal_entry_line', schema=None) as batch_op:
        batch_op.drop_constraint('fk_jel_gold_transaction', type_='foreignkey')
        batch_op.drop_column('gold_price_applied')
        batch_op.drop_column('gold_weight_equiv')
        batch_op.drop_column('gold_transaction_id')

    with op.batch_alter_table('invoice', schema=None) as batch_op:
        batch_op.drop_column('settlement_gold_weight')
        batch_op.drop_column('settlement_cash_amount')
        batch_op.drop_column('settlement_price_per_gram')
        batch_op.drop_column('settlement_date')
        batch_op.drop_column('settlement_method')
        batch_op.drop_column('settlement_status')
        batch_op.drop_column('avg_cost_total_snapshot')
        batch_op.drop_column('avg_cost_manufacturing_component')
        batch_op.drop_column('avg_cost_gold_component')
        batch_op.drop_column('avg_cost_per_gram_snapshot')

    with op.batch_alter_table('supplier', schema=None) as batch_op:
        batch_op.drop_column('last_gold_transaction_date')
        batch_op.drop_column('gold_balance_cash_equivalent')
        batch_op.drop_column('gold_balance_weight')

    op.drop_table('supplier_gold_transaction')
    op.drop_table('inventory_costing_config')