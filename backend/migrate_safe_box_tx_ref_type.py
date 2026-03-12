"""One-time data migration: re-tag SafeBoxTransaction rows that originated from
invoice payments.

These rows were historically created with ``ref_type='voucher'`` even when the
voucher was auto-generated from an invoice payment.  The clearing settlement
system queries ``ref_type='invoice_payment'`` to find pending settlements, so
these mis-tagged rows were invisible — making the entire auto-settlement
non-functional.

Usage:
    cd backend
    source venv/bin/activate
    python migrate_safe_box_tx_ref_type.py          # dry-run (default)
    python migrate_safe_box_tx_ref_type.py --apply   # actually update
"""

from __future__ import annotations

import sys

from app import app
from models import db, SafeBoxTransaction

DRY_RUN = '--apply' not in sys.argv


def migrate():
    with app.app_context():
        # Find all SafeBoxTransaction rows with ref_type='voucher' and a non-null
        # invoice_payment_id — these are the mis-tagged invoice payment rows.
        rows = (
            SafeBoxTransaction.query
            .filter(
                SafeBoxTransaction.ref_type == 'voucher',
                SafeBoxTransaction.invoice_payment_id.isnot(None),
            )
            .all()
        )

        print(f"Found {len(rows)} SafeBoxTransaction rows with ref_type='voucher' "
              f"and invoice_payment_id set.")

        if not rows:
            print("Nothing to migrate.")
            return

        for row in rows:
            print(f"  id={row.id}  safe_box_id={row.safe_box_id}  "
                  f"invoice_payment_id={row.invoice_payment_id}  "
                  f"ref_id={row.ref_id}  direction={row.direction}  "
                  f"amount_cash={row.amount_cash}")

        if DRY_RUN:
            print(f"\n[DRY RUN] Would update {len(rows)} rows. "
                  f"Run with --apply to commit changes.")
            return

        updated = 0
        for row in rows:
            row.ref_type = 'invoice_payment'
            updated += 1

        db.session.commit()
        print(f"\n[APPLIED] Updated {updated} rows: ref_type='voucher' -> 'invoice_payment'.")


if __name__ == '__main__':
    migrate()
