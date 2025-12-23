"""add_categories_table

Revision ID: c78d19e04615
Revises: 1013d133d694
Create Date: 2025-11-15 17:38:41.972228

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c78d19e04615'
down_revision: Union[str, Sequence[str], None] = '1013d133d694'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # إنشاء جدول التصنيفات
    op.create_table(
        'category',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    
    # إضافة عمود category_id في جدول items (SQLite لا يحتاج foreign key في migration)
    with op.batch_alter_table('item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('category_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # إزالة العمود من items
    with op.batch_alter_table('item', schema=None) as batch_op:
        batch_op.drop_column('category_id')
    
    # حذف جدول التصنيفات
    op.drop_table('category')
