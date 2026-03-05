"""add settlement_mode to payment_method

Revision ID: 20260305_settlement_mode_pm
Revises: 20260305_min_settlement_pm
Create Date: 2026-03-05 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = '20260305_settlement_mode_pm'
down_revision: Union[str, None] = '20260305_min_settlement_pm'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns(table: str):
    conn = op.get_bind()
    return {c['name'] for c in inspect(conn).get_columns(table)}


def upgrade() -> None:
    if 'settlement_mode' not in _existing_columns('payment_method'):
        op.add_column(
            'payment_method',
            sa.Column(
                'settlement_mode',
                sa.String(20),
                nullable=False,
                server_default='bulk',
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == 'sqlite':
        return
    if 'settlement_mode' in _existing_columns('payment_method'):
        op.drop_column('payment_method', 'settlement_mode')
