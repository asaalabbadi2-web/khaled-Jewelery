"""One-time data migration: re-tag SafeBoxTransaction rows that originated from
invoice payments.

These rows were historically created with ``ref_type='voucher'`` even when the
voucher was auto-generated from an invoice payment.  The clearing settlement
system queries ``ref_type='invoice_payment'`` to find pending settlements, so
these mis-tagged rows were invisible — making the entire auto-settlement
non-functional.

This migration fixes two historical issues:
1) SafeBoxTransaction.ref_type was stored as 'voucher' instead of 'invoice_payment'.
2) Some rows may have the invoice payment ID only inside Voucher.notes JSON,
   while SafeBoxTransaction.invoice_payment_id stayed NULL.

Usage:
    cd backend
    source venv/bin/activate
    python migrate_safe_box_tx_ref_type.py          # dry-run (default)
    python migrate_safe_box_tx_ref_type.py --apply   # actually update
"""

from __future__ import annotations

import json
import re
import sys

from app import app
from models import db, SafeBoxTransaction, Voucher

DRY_RUN = '--apply' not in sys.argv


_INVOICE_PAYMENT_ID_RE = re.compile(
    r'"(?:invoice_payment_id|invoicePaymentId)"\s*:\s*"?(\d+)"?'
)


def _extract_invoice_payment_id(notes: str | None) -> int | None:
    if not notes:
        return None

    raw = notes.strip()
    if not raw:
        return None

    # Best-effort parse as JSON.
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            # Support multiple key spellings from older deployments.
            for key in ('invoice_payment_id', 'invoicePaymentId'):
                val = parsed.get(key)
                if val not in (None, '', False):
                    return int(val)

            # Some notes might embed invoice payment under a nested object.
            nested = parsed.get('invoice_payment')
            if isinstance(nested, dict):
                nid = nested.get('id')
                if nid not in (None, '', False):
                    return int(nid)
    except Exception:
        pass

    # Fallback: regex search inside a larger string.
    m = _INVOICE_PAYMENT_ID_RE.search(raw)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def migrate():
    with app.app_context():
        # Candidates:
        # - ref_type='voucher'
        # - either invoice_payment_id is already set, or voucher.notes contains it
        rows = (
            SafeBoxTransaction.query
            .outerjoin(Voucher, Voucher.id == SafeBoxTransaction.ref_id)
            .filter(SafeBoxTransaction.ref_type == 'voucher')
            .filter(
                db.or_(
                    SafeBoxTransaction.invoice_payment_id.isnot(None),
                    db.and_(
                        SafeBoxTransaction.invoice_payment_id.is_(None),
                        Voucher.notes.isnot(None),
                        db.or_(
                            Voucher.notes.like('%invoice_payment_id%'),
                            Voucher.notes.like('%invoicePaymentId%'),
                        ),
                    ),
                )
            )
            .all()
        )

        print(
            f"Found {len(rows)} candidate SafeBoxTransaction rows with ref_type='voucher' "
            f"and invoice payment linkage (column or Voucher.notes)."
        )

        if not rows:
            print("Nothing to migrate.")
            return

        actionable = []
        for row in rows:
            voucher_notes = None
            if row.ref_id is not None:
                try:
                    v = Voucher.query.get(row.ref_id)
                    voucher_notes = v.notes if v else None
                except Exception:
                    voucher_notes = None

            recovered_ip_id = row.invoice_payment_id or _extract_invoice_payment_id(voucher_notes)
            if recovered_ip_id is None:
                continue
            actionable.append((row, recovered_ip_id))

        print(f"Actionable rows (will retag to invoice_payment): {len(actionable)}")

        for (row, recovered_ip_id) in actionable:
            print(
                f"  id={row.id}  safe_box_id={row.safe_box_id}  "
                f"invoice_payment_id={row.invoice_payment_id} -> {recovered_ip_id}  "
                f"ref_id={row.ref_id}  direction={row.direction}  "
                f"amount_cash={row.amount_cash}"
            )

        if DRY_RUN:
            print(f"\n[DRY RUN] Would update {len(actionable)} rows. "
                  f"Run with --apply to commit changes.")
            return

        updated = 0
        for (row, recovered_ip_id) in actionable:
            if row.invoice_payment_id is None:
                row.invoice_payment_id = recovered_ip_id
            row.ref_type = 'invoice_payment'
            updated += 1

        db.session.commit()
        print(
            f"\n[APPLIED] Updated {updated} rows: ref_type='voucher' -> 'invoice_payment' "
            f"(and recovered invoice_payment_id when missing)."
        )


if __name__ == '__main__':
    migrate()
