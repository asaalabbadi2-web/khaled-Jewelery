#!/usr/bin/env python3
"""One-time repair: post unposted imported sales invoices.

These invoices were imported from Excel but stayed unposted because
the below_cost or large_discount approval gate triggered (historical
data that doesn't need approval). This script:

1. Finds all sales invoices (بيع) that have is_posted=False
2. Shows a summary
3. With --apply, marks them as posted and also posts their journal entries

Usage (dry-run):
    cd backend
    python -m devtools.post_unposted_imported_invoices

Apply:
    python -m devtools.post_unposted_imported_invoices --apply
"""

import argparse
import sys
from datetime import datetime


def main() -> int:
    parser = argparse.ArgumentParser(description="Post unposted imported invoices")
    parser.add_argument("--apply", action="store_true", help="Actually mark as posted (default: dry-run)")
    parser.add_argument(
        "--invoice-type",
        default="بيع",
        help="Invoice type to target (default: بيع)",
    )
    args = parser.parse_args()

    from app import app  # type: ignore
    from models import db, Invoice, JournalEntry  # type: ignore

    with app.app_context():
        q = Invoice.query.filter(
            Invoice.is_posted == False,  # noqa: E712
            Invoice.invoice_type == args.invoice_type,
        )
        unposted = q.all()

        if not unposted:
            print("No unposted invoices found. Nothing to do.")
            return 0

        print(f"Found {len(unposted)} unposted '{args.invoice_type}' invoices:\n")
        print(f"{'ID':>6}  {'Date':>12}  {'Total':>14}  {'Weight':>10}  {'Employee':>20}  {'Posted By'}")
        print("-" * 90)

        for inv in unposted:
            date_str = inv.date.strftime("%Y-%m-%d") if inv.date else "N/A"
            total = float(inv.total or 0.0)
            weight = float(inv.total_weight or 0.0)
            emp_id = inv.employee_id or "-"
            posted_by = inv.posted_by or "-"
            print(f"{inv.id:>6}  {date_str:>12}  {total:>14.2f}  {weight:>10.3f}  {str(emp_id):>20}  {posted_by}")

        sum_total = sum(float(i.total or 0.0) for i in unposted)
        sum_weight = sum(float(i.total_weight or 0.0) for i in unposted)
        print("-" * 90)
        print(f"{'SUM':>6}  {'':>12}  {sum_total:>14.2f}  {sum_weight:>10.3f}")

        if not args.apply:
            print(f"\nDry-run only. Use --apply to post these {len(unposted)} invoices.")
            return 0

        now = datetime.now()
        posted_count = 0
        je_posted = 0

        for inv in unposted:
            inv.is_posted = True
            if not inv.posted_at:
                inv.posted_at = now
            if not inv.posted_by:
                inv.posted_by = "repair_script"

            # Restore amount_paid (approval gate zeroed it)
            if float(inv.amount_paid or 0.0) == 0.0 and float(inv.total or 0.0) > 0.0:
                inv.amount_paid = float(inv.total or 0.0)
                inv.status = "paid"

            posted_count += 1

            # Also post the associated journal entry if it exists and is unposted
            try:
                je = JournalEntry.query.filter_by(
                    reference_type='invoice',
                    reference_id=inv.id,
                    is_posted=False,
                ).first()
                if je:
                    je.is_posted = True
                    if hasattr(je, 'posted_at') and not je.posted_at:
                        je.posted_at = now
                    if hasattr(je, 'posted_by') and not je.posted_by:
                        je.posted_by = "repair_script"
                    je_posted += 1
            except Exception as exc:
                print(f"  WARNING: Could not post JE for invoice {inv.id}: {exc}")

        db.session.commit()
        print(f"\n✅ Posted {posted_count} invoices and {je_posted} journal entries.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
