"""Add is_draft field to journal_entry

Revision ID: db170a4761ae
Revises: 20260125_add_fixed_commission_to_payment_method
Create Date: 2026-02-01 01:18:07.693763

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'db170a4761ae'
down_revision: Union[str, Sequence[str], None] = '20260125_add_fixed_commission_to_payment_method'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add is_draft column to journal_entry table
    op.add_column('journal_entry', sa.Column('is_draft', sa.Boolean(), nullable=False, server_default='1'))
    # Create index for is_draft
    op.create_index(op.f('ix_journal_entry_is_draft'), 'journal_entry', ['is_draft'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop index
    op.drop_index(op.f('ix_journal_entry_is_draft'), table_name='journal_entry')
    # Drop column
    op.drop_column('journal_entry', 'is_draft')
