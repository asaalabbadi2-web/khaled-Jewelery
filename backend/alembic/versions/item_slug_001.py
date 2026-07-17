"""Add slug column to item table

Revision ID: item_slug_001
Revises: weight_type_field_001
Create Date: 2026-07-12

Adds a URL-safe `slug` column to the `item` table so the Commerce API can
serve human-readable product URLs (/products/gold-ring-21k) instead of
routing through item_code.

After applying this migration, populate slugs via:
    UPDATE item SET slug = lower(item_code) WHERE slug IS NULL;

Then update _item_slug() in apps/commerce-api/src/yasargold_commerce/routers/catalog.py
to return item.slug directly.
"""
from alembic import op
import sqlalchemy as sa

revision = 'item_slug_001'
down_revision = 'weight_type_field_001'
branch_labels = None
depends_on = None


def upgrade():
    # Nullable first so existing rows are not rejected; populate then add constraint.
    op.add_column('item', sa.Column('slug', sa.String(120), nullable=True))
    op.create_index('ix_item_slug', 'item', ['slug'], unique=True)


def downgrade():
    op.drop_index('ix_item_slug', table_name='item')
    op.drop_column('item', 'slug')
