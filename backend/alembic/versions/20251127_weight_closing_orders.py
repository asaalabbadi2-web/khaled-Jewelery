"""add weight closing order tables

Revision ID: 20251127_weight_closing_orders
Revises: 20251124_weight_closing
Create Date: 2025-11-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, func


# revision identifiers, used by Alembic.
revision: str = '20251127_weight_closing_orders'
down_revision: Union[str, Sequence[str], None] = '20251124_weight_closing'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


invoice_columns_to_add = [
    ('weight_closing_status', sa.String(length=20), "'not_initialized'"),
    ('weight_closing_main_karat', sa.Float(), '21.0'),
    ('weight_closing_total_weight', sa.Float(), '0'),
    ('weight_closing_executed_weight', sa.Float(), '0'),
    ('weight_closing_remaining_weight', sa.Float(), '0'),
    ('weight_closing_close_price', sa.Float(), '0'),
    ('weight_closing_order_number', sa.String(length=30), None),
    ('weight_closing_price_source', sa.String(length=20), None),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    invoice_columns = {col['name'] for col in inspector.get_columns('invoice')}
    with op.batch_alter_table('invoice', schema=None) as batch_op:
        for column_name, column_type, default in invoice_columns_to_add:
            if column_name not in invoice_columns:
                batch_op.add_column(sa.Column(column_name, column_type, nullable=False if default is not None else True, server_default=default))

    if not inspector.has_table('weight_closing_order'):
        op.create_table(
            'weight_closing_order',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('invoice_id', sa.Integer(), nullable=False),
            sa.Column('order_number', sa.String(length=30), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='open'),
            sa.Column('main_karat', sa.Float(), nullable=False, server_default='21'),
            sa.Column('price_source', sa.String(length=20), nullable=False, server_default='live'),
            sa.Column('close_price_per_gram', sa.Float(), nullable=False, server_default='0'),
            sa.Column('gold_value_cash', sa.Float(), nullable=False, server_default='0'),
            sa.Column('manufacturing_wage_cash', sa.Float(), nullable=False, server_default='0'),
            sa.Column('profit_weight_main_karat', sa.Float(), nullable=False, server_default='0'),
            sa.Column('total_cash_value', sa.Float(), nullable=False, server_default='0'),
            sa.Column('total_weight_main_karat', sa.Float(), nullable=False, server_default='0'),
            sa.Column('executed_weight_main_karat', sa.Float(), nullable=False, server_default='0'),
            sa.Column('remaining_weight_main_karat', sa.Float(), nullable=False, server_default='0'),
            sa.Column('valuation_journal_entry_id', sa.Integer(), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=func.now()),
            sa.ForeignKeyConstraint(['invoice_id'], ['invoice.id'], name='fk_weight_closing_order_invoice'),
            sa.ForeignKeyConstraint(['valuation_journal_entry_id'], ['journal_entry.id'], name='fk_weight_closing_order_valuation_journal_entry'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('invoice_id', name='uq_weight_closing_order_invoice_id'),
            sa.UniqueConstraint('order_number', name='uq_weight_closing_order_order_number'),
        )
        op.create_index('ix_weight_closing_order_invoice_id', 'weight_closing_order', ['invoice_id'], unique=False)
        op.create_index('ix_weight_closing_order_order_number', 'weight_closing_order', ['order_number'], unique=True)

    if not inspector.has_table('weight_closing_execution'):
        op.create_table(
            'weight_closing_execution',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('order_id', sa.Integer(), nullable=False),
            sa.Column('source_invoice_id', sa.Integer(), nullable=True),
            sa.Column('execution_type', sa.String(length=30), nullable=False, server_default='purchase_scrap'),
            sa.Column('weight_main_karat', sa.Float(), nullable=False, server_default='0'),
            sa.Column('price_per_gram', sa.Float(), nullable=False, server_default='0'),
            sa.Column('difference_value', sa.Float(), nullable=False, server_default='0'),
            sa.Column('difference_weight', sa.Float(), nullable=False, server_default='0'),
            sa.Column('journal_entry_id', sa.Integer(), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=func.now()),
            sa.ForeignKeyConstraint(['order_id'], ['weight_closing_order.id'], name='fk_weight_closing_execution_order'),
            sa.ForeignKeyConstraint(['source_invoice_id'], ['invoice.id'], name='fk_weight_closing_execution_invoice'),
            sa.ForeignKeyConstraint(['journal_entry_id'], ['journal_entry.id'], name='fk_weight_closing_execution_journal_entry'),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_weight_closing_execution_order_id', 'weight_closing_execution', ['order_id'], unique=False)
        op.create_index('ix_weight_closing_execution_source_invoice_id', 'weight_closing_execution', ['source_invoice_id'], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table('weight_closing_execution'):
        op.drop_index('ix_weight_closing_execution_source_invoice_id', table_name='weight_closing_execution')
        op.drop_index('ix_weight_closing_execution_order_id', table_name='weight_closing_execution')
        op.drop_table('weight_closing_execution')

    if inspector.has_table('weight_closing_order'):
        op.drop_index('ix_weight_closing_order_order_number', table_name='weight_closing_order')
        op.drop_index('ix_weight_closing_order_invoice_id', table_name='weight_closing_order')
        op.drop_table('weight_closing_order')

    invoice_columns = {col['name'] for col in inspector.get_columns('invoice')}
    with op.batch_alter_table('invoice', schema=None) as batch_op:
        for column_name, _, _ in invoice_columns_to_add:
            if column_name in invoice_columns:
                batch_op.drop_column(column_name)
