"""Add DB-level guard to prevent orphan invoice_payment safe_box_transaction rows.

This protects against the production class of bugs where SafeBoxTransaction rows
were created for invoice payments without proper references (ref_id / invoice_payment_id).

We add a CHECK constraint as NOT VALID so existing legacy rows are not validated,
while new inserts/updates are enforced immediately.

Revision ID: 20260313_add_sbt_invoice_payment_ref_guard
Revises: (20260305_settlement_mode_pm, 20260307_add_category_id_to_invoice_item, 20260309_sales_race)
Create Date: 2026-03-13
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = '20260313_add_sbt_invoice_payment_ref_guard'
down_revision = (
    '20260305_settlement_mode_pm',
    '20260307_add_category_id_to_invoice_item',
    '20260309_sales_race',
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE safe_box_transaction
        ADD CONSTRAINT chk_sbt_invoice_payment_refs
        CHECK (
          ref_type IS DISTINCT FROM 'invoice_payment'
          OR (
            invoice_payment_id IS NOT NULL
            AND ref_id IS NOT NULL
          )
        )
        NOT VALID;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE safe_box_transaction
        DROP CONSTRAINT IF EXISTS chk_sbt_invoice_payment_refs;
        """
    )
