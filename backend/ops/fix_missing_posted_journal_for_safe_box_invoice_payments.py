"""Operational repair: create missing posted journal entries for clearing safe-box invoice payments.

Context:
- Dashboard/safe-box list uses live balances computed from posted journal entries
  (see services/live_balances.py).
- Some production incidents created SafeBoxTransaction rows (ref_type=invoice_payment)
  with ref_id=NULL (no voucher), meaning the safe ledger shows money but the
  posted journal does not.

This script generates *posted* JournalEntry + JournalEntryLine rows for those
transactions, without adding any new SafeBoxTransaction rows (avoids duplication).

Usage (inside backend container /app):
  python3 /app/backend/ops/fix_missing_posted_journal_for_safe_box_invoice_payments.py --safe-box-id 35 --apply

Dry run:
  python3 /app/backend/ops/fix_missing_posted_journal_for_safe_box_invoice_payments.py --safe-box-id 35
"""

from __future__ import annotations

import argparse
from datetime import datetime

from app import app
from models import (
    Customer,
    Invoice,
    InvoicePayment,
    JournalEntry,
    JournalEntryLine,
    SafeBox,
    SafeBoxTransaction,
    Supplier,
    db,
)
from party_account_service import ensure_customer_accounts, ensure_supplier_accounts


def _to_float(v, default: float = 0.0) -> float:
    try:
        if v in (None, ""):
            return default
        return float(v)
    except Exception:
        return default


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--safe-box-id", type=int, required=True)
    parser.add_argument("--created-by", type=str, default="ops-fix")
    parser.add_argument("--apply", action="store_true", help="Actually write changes")
    args = parser.parse_args()

    safe_box_id = int(args.safe_box_id)
    created_by = (args.created_by or "ops-fix").strip() or "ops-fix"
    apply = bool(args.apply)

    with app.app_context():
        sb = SafeBox.query.get(safe_box_id)
        if not sb:
            print(f"ERROR: safe_box_id={safe_box_id} not found")
            return 2
        if not getattr(sb, "account_id", None):
            print(f"ERROR: safe_box_id={safe_box_id} has no account_id")
            return 2

        safe_account_id = int(sb.account_id)

        txs = (
            SafeBoxTransaction.query
            .filter(SafeBoxTransaction.safe_box_id == safe_box_id)
            .filter(SafeBoxTransaction.ref_type == "invoice_payment")
            .filter(SafeBoxTransaction.ref_id.is_(None))
            .order_by(SafeBoxTransaction.id.asc())
            .all()
        )

        if not txs:
            print("OK: no candidate SafeBoxTransaction rows (ref_id IS NULL)")
            return 0

        print(f"Found {len(txs)} candidate tx rows for safe_box_id={safe_box_id} ({sb.name})")

        planned = []
        skipped = []
        errors = []

        now = datetime.now()

        for tx in txs:
            tx_id = int(tx.id)
            direction = (tx.direction or "in").strip().lower() or "in"
            amount = _to_float(getattr(tx, "amount_cash", None), 0.0)
            if amount <= 0:
                skipped.append((tx_id, "non_positive_amount"))
                continue

            ip_id = getattr(tx, "invoice_payment_id", None)
            if ip_id in (None, "", 0, False):
                skipped.append((tx_id, "missing_invoice_payment_id"))
                continue
            ip_id = int(ip_id)

            existing_any = (
                JournalEntry.query
                .filter(JournalEntry.reference_id == ip_id)
                .filter(JournalEntry.reference_type.in_(["invoice_payment", "invoice_payment_fix"]))
                .filter(JournalEntry.is_deleted == False)
                .first()
            )
            if existing_any:
                skipped.append((tx_id, f"already_has_je:je_id={existing_any.id}") )
                continue

            invoice_id = getattr(tx, "invoice_id", None)
            if invoice_id in (None, "", 0, False):
                skipped.append((tx_id, "missing_invoice_id"))
                continue
            invoice_id = int(invoice_id)

            inv = Invoice.query.get(invoice_id)
            if not inv:
                skipped.append((tx_id, f"invoice_not_found:{invoice_id}"))
                continue

            party_account_id = None
            customer_id = None
            supplier_id = None
            try:
                if getattr(inv, "supplier_id", None):
                    supplier_id = int(inv.supplier_id)
                    supplier = Supplier.query.get(supplier_id)
                    if not supplier:
                        raise ValueError("supplier_not_found")
                    party_account_id = int(ensure_supplier_accounts(supplier).financial.id)
                elif getattr(inv, "customer_id", None):
                    customer_id = int(inv.customer_id)
                    customer = Customer.query.get(customer_id)
                    if not customer:
                        raise ValueError("customer_not_found")
                    party_account_id = int(ensure_customer_accounts(customer).financial.id)
                else:
                    raise ValueError("missing_party")
            except Exception as exc:
                errors.append((tx_id, f"party_account_resolve_failed:{exc}"))
                continue

            tx_dt = getattr(tx, "created_at", None) or now
            inv_number = getattr(inv, "invoice_number", None) or str(getattr(inv, "invoice_type_id", "") or "") or None

            desc = (
                f"Fix missing posted JE for safe invoice payment: safe_box_id={safe_box_id}, "
                f"safe_tx_id={tx_id}, invoice_id={invoice_id}, invoice_payment_id={ip_id}"
            )

            # Build JE + 2 lines.
            je = JournalEntry(
                date=tx_dt,
                description=desc,
                entry_type="تصحيح",
                reference_type="invoice_payment_fix",
                reference_id=ip_id,
                reference_number=inv_number,
                created_by=created_by,
                is_draft=False,
                is_posted=True,
                posted_at=now,
                posted_by=created_by,
                is_deleted=False,
            )

            # Direction: 'in' means money came into the safe account.
            safe_debit = amount if direction == "in" else 0.0
            safe_credit = amount if direction != "in" else 0.0
            party_debit = safe_credit
            party_credit = safe_debit

            safe_line = JournalEntryLine(
                journal_entry=je,
                account_id=safe_account_id,
                cash_debit=safe_debit,
                cash_credit=safe_credit,
                description=f"SafeBox {sb.name} (auto-fix)",
            )

            party_line = JournalEntryLine(
                journal_entry=je,
                account_id=int(party_account_id),
                customer_id=customer_id,
                supplier_id=supplier_id,
                cash_debit=party_debit,
                cash_credit=party_credit,
                description="Party (auto-fix)",
            )

            planned.append((tx_id, ip_id, invoice_id, amount, direction, safe_line, party_line, je))

        if not planned and not errors:
            print("OK: nothing to fix")
            if skipped:
                print(f"Skipped: {len(skipped)}")
            return 0

        print(f"Planned fixes: {len(planned)}")
        if skipped:
            print(f"Skipped: {len(skipped)}")
        if errors:
            print(f"Errors: {len(errors)}")

        total_amount = sum(p[3] for p in planned)
        print(f"Planned total amount: {total_amount:.2f}")

        if not apply:
            print("DRY RUN: no DB writes (pass --apply to execute)")
            return 0

        try:
            for (_tx_id, _ip_id, _inv_id, _amt, _dir, safe_line, party_line, je) in planned:
                db.session.add(je)
                db.session.add(safe_line)
                db.session.add(party_line)

            db.session.commit()
            print(f"APPLIED: created {len(planned)} posted journal entries")
        except Exception as exc:
            db.session.rollback()
            print(f"ERROR: failed to apply fixes: {exc}")
            return 1

        return 0


if __name__ == "__main__":
    raise SystemExit(main())
