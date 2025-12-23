"""merge_heads_post_purchase_invoice

Revision ID: 88b0f70d99e9
Revises: 20251124_add_weight_closing_settings, 20251128_add_purchase_invoice_id_to_office_reservation, c745c5513330
Create Date: 2025-11-28 14:28:32.130270

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '88b0f70d99e9'
down_revision: Union[str, Sequence[str], None] = ('20251124_add_weight_closing_settings', '20251128_add_purchase_invoice_id_to_office_reservation', 'c745c5513330')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
