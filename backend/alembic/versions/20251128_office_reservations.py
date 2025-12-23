"""add office reservation tracking

Revision ID: 20251128_office_reservations
Revises: 20251127_weight_closing_orders
Create Date: 2025-11-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import func, inspect


# revision identifiers, used by Alembic.
revision: str = '20251128_office_reservations'
down_revision: Union[str, Sequence[str], None] = '20251127_weight_closing_orders'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    office_columns = {col['name'] for col in inspector.get_columns('office')}

    with op.batch_alter_table('office', schema=None) as batch_op:
        if 'total_reservations' not in office_columns:
            batch_op.add_column(sa.Column('total_reservations', sa.Integer(), nullable=False, server_default='0'))
        if 'total_weight_purchased' not in office_columns:
            batch_op.add_column(sa.Column('total_weight_purchased', sa.Float(), nullable=False, server_default='0'))
        if 'total_amount_paid' not in office_columns:
            batch_op.add_column(sa.Column('total_amount_paid', sa.Float(), nullable=False, server_default='0'))

    existing_tables = inspector.get_table_names()
    if 'office_reservation' not in existing_tables:
        op.create_table(
            'office_reservation',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('office_id', sa.Integer(), nullable=False),
            sa.Column('reservation_code', sa.String(length=30), nullable=False),
            sa.Column('reservation_date', sa.DateTime(), nullable=False, server_default=func.now()),
            sa.Column('karat', sa.Integer(), nullable=False, server_default='24'),
            sa.Column('weight_grams', sa.Float(), nullable=False),
            sa.Column('weight_main_karat', sa.Float(), nullable=False),
            sa.Column('price_per_gram', sa.Float(), nullable=False),
            sa.Column('execution_price_per_gram', sa.Float(), nullable=False),
            sa.Column('total_amount', sa.Float(), nullable=False),
            sa.Column('paid_amount', sa.Float(), nullable=False, server_default='0'),
            sa.Column('payment_status', sa.String(length=20), nullable=False, server_default='pending'),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='reserved'),
            sa.Column('contact_person', sa.String(length=100), nullable=True),
            sa.Column('contact_phone', sa.String(length=50), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('executions_created', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('weight_consumed_main_karat', sa.Float(), nullable=False, server_default='0'),
            sa.Column('weight_remaining_main_karat', sa.Float(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=func.now()),
            sa.ForeignKeyConstraint(['office_id'], ['office.id'], name='fk_office_reservation_office'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('reservation_code', name='uq_office_reservation_code'),
        )
        op.create_index('ix_office_reservation_office_id', 'office_reservation', ['office_id'], unique=False)
    else:
        existing_indexes = {idx['name'] for idx in inspector.get_indexes('office_reservation')}
        if 'ix_office_reservation_office_id' not in existing_indexes:
            op.create_index('ix_office_reservation_office_id', 'office_reservation', ['office_id'], unique=False)

    # Drop server defaults now that data is backfilled (only if columns exist)
    office_columns_after = {col['name'] for col in inspector.get_columns('office')}
    with op.batch_alter_table('office', schema=None) as batch_op:
        if 'total_reservations' in office_columns_after:
            batch_op.alter_column('total_reservations', server_default=None)
        if 'total_weight_purchased' in office_columns_after:
            batch_op.alter_column('total_weight_purchased', server_default=None)
        if 'total_amount_paid' in office_columns_after:
            batch_op.alter_column('total_amount_paid', server_default=None)


def downgrade() -> None:
    op.drop_index('ix_office_reservation_office_id', table_name='office_reservation')
    op.drop_table('office_reservation')

    with op.batch_alter_table('office', schema=None) as batch_op:
        batch_op.drop_column('total_amount_paid')
        batch_op.drop_column('total_weight_purchased')
        batch_op.drop_column('total_reservations')
