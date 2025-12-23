"""add wage inventory fields to invoice

Revision ID: 20251205_add_wage_inventory_fields_to_invoice
Revises: 20251202_allow_manual_invoice_items
Create Date: 2025-12-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '20251205_add_wage_inventory_fields_to_invoice'
down_revision: Union[str, Sequence[str], None] = '20251202_allow_manual_invoice_items'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col['name'] for col in inspector.get_columns('invoice')}
    fk_names = {fk.get('name') for fk in inspector.get_foreign_keys('invoice') if fk.get('name')}

    added_balance_column = False

    with op.batch_alter_table('invoice', schema=None) as batch_op:
        if 'manufacturing_wage_mode_snapshot' not in columns:
            batch_op.add_column(
                sa.Column('manufacturing_wage_mode_snapshot', sa.String(length=20), nullable=True)
            )

        if 'wage_inventory_account_id' not in columns:
            batch_op.add_column(sa.Column('wage_inventory_account_id', sa.Integer(), nullable=True))
            if 'fk_invoice_wage_inventory_account' not in fk_names:
                batch_op.create_foreign_key(
                    'fk_invoice_wage_inventory_account',
                    'account',
                    ['wage_inventory_account_id'],
                    ['id']
                )

        if 'wage_inventory_balance_main_karat' not in columns:
            batch_op.add_column(
                sa.Column(
                    'wage_inventory_balance_main_karat',
                    sa.Float(),
                    nullable=False,
                    server_default='0'
                )
            )
            added_balance_column = True

    if added_balance_column:
        with op.batch_alter_table('invoice', schema=None) as batch_op:
            batch_op.alter_column('wage_inventory_balance_main_karat', server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col['name'] for col in inspector.get_columns('invoice')}
    fk_names = {fk.get('name') for fk in inspector.get_foreign_keys('invoice') if fk.get('name')}

    with op.batch_alter_table('invoice', schema=None) as batch_op:
        if 'fk_invoice_wage_inventory_account' in fk_names:
            batch_op.drop_constraint('fk_invoice_wage_inventory_account', type_='foreignkey')

        if 'wage_inventory_account_id' in columns:
            batch_op.drop_column('wage_inventory_account_id')

        if 'manufacturing_wage_mode_snapshot' in columns:
            batch_op.drop_column('manufacturing_wage_mode_snapshot')

        if 'wage_inventory_balance_main_karat' in columns:
            batch_op.drop_column('wage_inventory_balance_main_karat')
