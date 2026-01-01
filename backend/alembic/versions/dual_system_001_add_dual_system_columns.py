"""add dual system columns

Revision ID: dual_system_001
Revises: 
Create Date: 2025-12-02 21:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'dual_system_001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # إضافة أعمدة النظام المزدوج لـ JournalEntryLine
    with op.batch_alter_table('journal_entry_line', schema=None) as batch_op:
        batch_op.add_column(sa.Column('debit_weight', sa.Float(), nullable=True, server_default='0.0'))
        batch_op.add_column(sa.Column('credit_weight', sa.Float(), nullable=True, server_default='0.0'))
        batch_op.add_column(sa.Column('gold_price_snapshot', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('description', sa.String(length=500), nullable=True))
    
    # إضافة حقل memo_account_id لـ Account
    with op.batch_alter_table('account', schema=None) as batch_op:
        batch_op.add_column(sa.Column('memo_account_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_account_memo', 'account', ['memo_account_id'], ['id'])


def downgrade():
    # إزالة الأعمدة
    with op.batch_alter_table('journal_entry_line', schema=None) as batch_op:
        batch_op.drop_column('description')
        batch_op.drop_column('gold_price_snapshot')
        batch_op.drop_column('credit_weight')
        batch_op.drop_column('debit_weight')
    
    with op.batch_alter_table('account', schema=None) as batch_op:
        batch_op.drop_constraint('fk_account_memo', type_='foreignkey')
        batch_op.drop_column('memo_account_id')
