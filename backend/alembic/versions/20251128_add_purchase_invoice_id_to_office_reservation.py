"""add purchase_invoice_id to office_reservation

Revision ID: 20251128_add_purchase_invoice_id_to_office_reservation
Revises: 20251128_office_reservations
Create Date: 2025-11-28 00:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20251128_add_purchase_invoice_id_to_office_reservation'
down_revision: Union[str, Sequence[str], None] = '20251128_office_reservations'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('office_reservation', schema=None) as batch_op:
        batch_op.add_column(sa.Column('purchase_invoice_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_office_reservation_purchase_invoice', 'invoice', ['purchase_invoice_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('office_reservation', schema=None) as batch_op:
        batch_op.drop_constraint('fk_office_reservation_purchase_invoice', type_='foreignkey')
        batch_op.drop_column('purchase_invoice_id'
)
