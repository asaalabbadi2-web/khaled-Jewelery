"""Expand currency_symbol column from VARCHAR(10) to VARCHAR(20)

Revision ID: expand_currency_symbol_001
Revises: weight_type_field_001
Create Date: 2026-05-07 10:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'expand_currency_symbol_001'
down_revision = 'weight_type_field_001'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        'settings',
        'currency_symbol',
        existing_type=sa.String(10),
        type_=sa.String(20),
        existing_nullable=True,
    )


def downgrade():
    op.alter_column(
        'settings',
        'currency_symbol',
        existing_type=sa.String(20),
        type_=sa.String(10),
        existing_nullable=True,
    )
