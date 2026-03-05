"""add fee_expense_account_id to payment_method

Revision ID: 20260305_fee_expense_pm
Revises: 20260305_posting_settings
Create Date: 2026-03-05 00:01:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = '20260305_fee_expense_pm'
down_revision: Union[str, None] = '20260305_posting_settings'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns(table: str):
    conn = op.get_bind()
    return {c['name'] for c in inspect(conn).get_columns(table)}


def upgrade() -> None:
    if 'fee_expense_account_id' not in _existing_columns('payment_method'):
        op.add_column(
            'payment_method',
            sa.Column(
                'fee_expense_account_id',
                sa.Integer(),
                sa.ForeignKey('account.id', ondelete='SET NULL'),
                nullable=True,
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == 'sqlite':
        return
    if 'fee_expense_account_id' in _existing_columns('payment_method'):
        op.drop_column('payment_method', 'fee_expense_account_id')
