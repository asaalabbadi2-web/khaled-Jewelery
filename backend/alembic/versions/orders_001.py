"""Create orders table

Revision ID: orders_001
Revises: reservation_outbox_001
Create Date: 2026-07-13

Adds one new table owned by the Commerce API write side:

  orders — one row per confirmed sale. Created atomically with
           Reservation transitioning to COMPLETED via CheckoutUnitOfWork.

           reservation_id has a UNIQUE constraint — one Order per Reservation.
           payment_intent_id is indexed for webhook-side lookups.

Inventory note:
  The item_id column is a reference to the ERP items table.
  The ERP consumer of OrderCreated marks the item as SOLD — Commerce API
  does NOT write to the items table directly (Single Writer principle).

Status values:
  PENDING | CONFIRMED | READY_FOR_SHIPMENT | SHIPPED | DELIVERED | CANCELLED
"""
from alembic import op
import sqlalchemy as sa

revision = 'orders_001'
down_revision = 'reservation_outbox_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'orders',
        sa.Column('id', sa.String(40), primary_key=True),
        sa.Column('reservation_id', sa.String(40), nullable=False, unique=True),
        sa.Column('payment_intent_id', sa.String(40), nullable=False),
        sa.Column('item_id', sa.Integer, nullable=False),
        sa.Column('amount', sa.Numeric(14, 2), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False, server_default='SAR'),
        sa.Column('status', sa.String(30), nullable=False, server_default='CONFIRMED'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('shipped_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancellation_reason', sa.Text, nullable=True),
    )
    op.create_index('ix_orders_reservation_id', 'orders', ['reservation_id'], unique=True)
    op.create_index('ix_orders_payment_intent_id', 'orders', ['payment_intent_id'])
    op.create_index('ix_orders_status', 'orders', ['status'])


def downgrade() -> None:
    op.drop_index('ix_orders_status', table_name='orders')
    op.drop_index('ix_orders_payment_intent_id', table_name='orders')
    op.drop_index('ix_orders_reservation_id', table_name='orders')
    op.drop_table('orders')
