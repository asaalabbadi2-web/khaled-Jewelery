"""add allow_partial_invoice_payments flag

Revision ID: 20251227_allow_partial_invoice_payments
Revises: 20251205_add_wage_inventory_fields_to_invoice
Create Date: 2025-12-27 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '20251227_allow_partial_invoice_payments'
down_revision: Union[str, Sequence[str], None] = '20251205_add_wage_inventory_fields_to_invoice'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col['name'] for col in inspector.get_columns('settings')}

    if 'allow_partial_invoice_payments' not in columns:
        with op.batch_alter_table('settings', schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    'allow_partial_invoice_payments',
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )

        op.execute("UPDATE settings SET allow_partial_invoice_payments = 0")

        with op.batch_alter_table('settings', schema=None) as batch_op:
            batch_op.alter_column(
                'allow_partial_invoice_payments',
                server_default=None,
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col['name'] for col in inspector.get_columns('settings')}

    if 'allow_partial_invoice_payments' in columns:
        with op.batch_alter_table('settings', schema=None) as batch_op:
            batch_op.drop_column('allow_partial_invoice_payments')
