"""link offices to suppliers

Revision ID: 20251128_office_supplier_link
Revises: 88b0f70d99e9
Create Date: 2025-11-28 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = '20251128_office_supplier_link'
down_revision: Union[str, Sequence[str], None] = '88b0f70d99e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _next_supplier_code(current: str) -> str:
    base = 0
    if current:
        try:
            base = int(str(current).split('-')[1])
        except (IndexError, ValueError, AttributeError):
            base = 0
    return f"S-{base + 1:06d}"


def upgrade() -> None:
    with op.batch_alter_table('office', schema=None) as batch_op:
        batch_op.add_column(sa.Column('supplier_id', sa.Integer(), nullable=True))
        batch_op.create_unique_constraint('uq_office_supplier_id', ['supplier_id'])
        batch_op.create_foreign_key('fk_office_supplier', 'supplier', ['supplier_id'], ['id'])

    bind = op.get_bind()
    session = Session(bind=bind)
    metadata = sa.MetaData()
    office_table = sa.Table('office', metadata, autoload_with=bind)
    supplier_table = sa.Table('supplier', metadata, autoload_with=bind)

    last_code = session.execute(
        sa.select(supplier_table.c.supplier_code)
        .where(supplier_table.c.supplier_code.isnot(None))
        .order_by(supplier_table.c.id.desc())
        .limit(1)
    ).scalar()

    offices = session.execute(
        sa.select(
            office_table.c.id,
            office_table.c.office_code,
            office_table.c.name,
            office_table.c.phone,
            office_table.c.email,
            office_table.c.account_category_id,
            office_table.c.active,
            office_table.c.supplier_id,
        ).where(office_table.c.supplier_id.is_(None))
    ).all()

    current_code = last_code or 'S-000000'
    for office in offices:
        current_code = _next_supplier_code(current_code)
        result = session.execute(
            supplier_table.insert()
            .values(
                supplier_code=current_code,
                name=office.name or f"Office #{office.id}",
                phone=office.phone,
                email=office.email,
                account_category_id=office.account_category_id,
                notes=f"Auto-created for office {office.office_code}",
                active=office.active,
                balance_cash=0.0,
                balance_gold_18k=0.0,
                balance_gold_21k=0.0,
                balance_gold_22k=0.0,
                balance_gold_24k=0.0,
                gold_balance_weight=0.0,
                gold_balance_cash_equivalent=0.0,
            )
        )
        supplier_id = result.inserted_primary_key[0]
        session.execute(
            office_table.update()
            .where(office_table.c.id == office.id)
            .values(supplier_id=supplier_id)
        )

    session.commit()


def downgrade() -> None:
    with op.batch_alter_table('office', schema=None) as batch_op:
        batch_op.drop_constraint('fk_office_supplier', type_='foreignkey')
        batch_op.drop_constraint('uq_office_supplier_id', type_='unique')
        batch_op.drop_column('supplier_id')
