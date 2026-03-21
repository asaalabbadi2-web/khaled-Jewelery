"""Add company_cr_number to Settings.

Revision ID: 20260319_add_company_cr_number_to_settings
Revises: 20260313_add_sbt_invoice_payment_ref_guard
Create Date: 2026-03-19
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260319_add_company_cr_number_to_settings'
down_revision = '20260313_add_sbt_invoice_payment_ref_guard'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('settings', sa.Column('company_cr_number', sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column('settings', 'company_cr_number')
