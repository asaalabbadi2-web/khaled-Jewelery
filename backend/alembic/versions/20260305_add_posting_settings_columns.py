"""add auto_post_invoices / auto_post_entries / require_approval_before_post / allow_unposting to settings

Revision ID: 20260305_posting_settings
Revises: 92f5e99c571a
Create Date: 2026-03-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = '20260305_posting_settings'
down_revision: Union[str, None] = '92f5e99c571a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns(table: str):
    conn = op.get_bind()
    insp = inspect(conn)
    return {c['name'] for c in insp.get_columns(table)}


def upgrade() -> None:
    existing = _existing_columns('settings')

    if 'auto_post_invoices' not in existing:
        op.add_column('settings', sa.Column('auto_post_invoices', sa.Boolean(), nullable=True, server_default=sa.text('1')))

    if 'auto_post_entries' not in existing:
        op.add_column('settings', sa.Column('auto_post_entries', sa.Boolean(), nullable=True, server_default=sa.text('1')))

    if 'require_approval_before_post' not in existing:
        op.add_column('settings', sa.Column('require_approval_before_post', sa.Boolean(), nullable=True, server_default=sa.text('0')))

    if 'allow_unposting' not in existing:
        op.add_column('settings', sa.Column('allow_unposting', sa.Boolean(), nullable=True, server_default=sa.text('0')))


def downgrade() -> None:
    # SQLite does not support DROP COLUMN on older versions; skip gracefully.
    conn = op.get_bind()
    if conn.dialect.name == 'sqlite':
        return
    existing = _existing_columns('settings')
    for col in ('allow_unposting', 'require_approval_before_post', 'auto_post_entries', 'auto_post_invoices'):
        if col in existing:
            op.drop_column('settings', col)
