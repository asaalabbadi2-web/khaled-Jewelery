"""Create reservations and outbox_events tables

Revision ID: reservation_outbox_001
Revises: item_slug_001
Create Date: 2026-07-13

Adds two new tables owned by the Commerce API write side:

  reservations   — one row per confirmed reservation; source of truth for
                   inventory lock status. status IN ('ACTIVE', 'EXPIRED',
                   'CANCELLED', 'COMPLETED').

  outbox_events  — transactional outbox for domain events. The background
                   Worker polls this table, publishes events, and sets
                   published_at. At-least-once delivery; consumers deduplicate
                   on event_id (UUID).

Locking note:
  To enforce single-reservation-per-item at the DB level (INV-6), add after
  data is populated:
      CREATE UNIQUE INDEX ix_reservations_active_item
          ON reservations (item_id)
          WHERE status = 'ACTIVE';
  This partial unique index, combined with SELECT FOR UPDATE NOWAIT in
  SQLAlchemyInventoryRepository.lock_item(), prevents double-reservation
  under concurrent writes.
"""
from alembic import op
import sqlalchemy as sa

revision = 'reservation_outbox_001'
down_revision = 'item_slug_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'reservations',
        sa.Column('id', sa.String(40), primary_key=True),
        sa.Column('quote_id', sa.String(40), nullable=False),
        sa.Column('item_id', sa.Integer, nullable=False),
        sa.Column('gold_price_id', sa.Integer, nullable=False),
        sa.Column('locked_rate_per_gram_24k', sa.Numeric(14, 6), nullable=False),
        sa.Column('karat_rate_per_gram', sa.Numeric(14, 6), nullable=False),
        sa.Column('pricing_engine_version', sa.String(20), nullable=False),
        sa.Column('reserved_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('valid_until', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='ACTIVE'),
    )
    op.create_index('ix_reservations_quote_id', 'reservations', ['quote_id'])
    op.create_index('ix_reservations_item_id', 'reservations', ['item_id'])
    op.create_index('ix_reservations_valid_until', 'reservations', ['valid_until'])
    # INV-6: Partial unique index — enforces single ACTIVE reservation per item.
    # Combined with SELECT FOR UPDATE NOWAIT in lock_item(), this is a two-layer
    # defence: the SELECT catches the common case, the index catches INSERT races.
    # PostgreSQL only; other dialects skip this silently (partial unique unsupported).
    op.create_index(
        'ix_reservations_active_item',
        'reservations',
        ['item_id'],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )

    op.create_table(
        'outbox_events',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('event_id', sa.String(36), nullable=False, unique=True),
        sa.Column('event_type', sa.String(200), nullable=False),
        sa.Column('payload', sa.Text, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_outbox_event_id', 'outbox_events', ['event_id'], unique=True)
    op.create_index(
        'ix_outbox_unpublished',
        'outbox_events',
        ['created_at'],
        postgresql_where=sa.text("published_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index('ix_reservations_active_item', table_name='reservations')
    op.drop_table('outbox_events')
    op.drop_table('reservations')
