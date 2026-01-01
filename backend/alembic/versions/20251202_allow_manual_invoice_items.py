"""add allow_manual_invoice_items flag

Revision ID: 20251202_allow_manual_invoice_items
Revises: 20251128_add_purchase_invoice_id_to_office_reservation
Create Date: 2025-12-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '20251202_allow_manual_invoice_items'
down_revision: Union[str, Sequence[str], None] = '20251128_add_purchase_invoice_id_to_office_reservation'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col['name'] for col in inspector.get_columns('settings')}

    if 'allow_manual_invoice_items' not in columns:
        with op.batch_alter_table('settings', schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    'allow_manual_invoice_items',
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.true(),
                )
            )

        op.execute("UPDATE settings SET allow_manual_invoice_items = 1")

    # Remove the explicit server default so ORM-level defaults stay authoritative
        with op.batch_alter_table('settings', schema=None) as batch_op:
            batch_op.alter_column(
                'allow_manual_invoice_items',
                server_default=None,
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col['name'] for col in inspector.get_columns('settings')}

    if 'allow_manual_invoice_items' in columns:
        with op.batch_alter_table('settings', schema=None) as batch_op:
            batch_op.drop_column('allow_manual_invoice_items')
