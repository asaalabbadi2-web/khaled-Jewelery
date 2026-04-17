"""add settlement_line table

Revision ID: 20260417_settlement_line
Revises: 20260330_costing_type_001
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '20260417_settlement_line'
down_revision = '20260330_costing_type_001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'settlement_line',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('voucher_id', sa.Integer(), sa.ForeignKey('voucher.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('invoice_payment_id', sa.Integer(), sa.ForeignKey('invoice_payment.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('amount_settled', sa.Float(), nullable=False),
        sa.Column('commission', sa.Float(), server_default='0'),
        sa.Column('commission_vat', sa.Float(), server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table('settlement_line')
