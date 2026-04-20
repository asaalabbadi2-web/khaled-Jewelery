#!/usr/bin/env python3
"""Fix return invoices recorded before the VAT-split fix.

Problem
-------
Return invoices (مرتجع بيع / مرتجع شراء) created before the backend fix had
tax = 0 passed to the JE engine because the frontend did not send `tax_amount`
on each item. This caused the JE to debit/credit the full amount against the
sales/purchase returns account instead of splitting it into:
  - net amount  → مردودات المبيعات / مردودات المشتريات
  - tax amount  → ضريبة القيمة المضافة (payable / receivable)

Correction
----------
For each affected return invoice (total_tax > 0, no VAT JE line):

  مرتجع بيع:
    Reduce  DR  مردودات المبيعات  by  total_tax
    Add new DR  ضريبة ق.م.         =  total_tax

  مرتجع شراء:
    Reduce  CR  مردودات المشتريات  by  total_tax
    Add new CR  ضريبة ق.م. (receivable) = total_tax

The JE total stays balanced (same debit total = same credit total).

Usage (inside Docker container)
--------------------------------
# Dry-run — show what would change, no DB writes:
    docker compose exec backend python backend/devtools/fix_return_invoice_vat.py

# Apply:
    docker compose exec backend python backend/devtools/fix_return_invoice_vat.py --apply

# Limit to a date range:
    docker compose exec backend python backend/devtools/fix_return_invoice_vat.py \\
        --start 2025-01-01 --end 2026-04-20 --apply
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime
from typing import Optional

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _resolve_account(session, operation_type: str, account_type: str, fallback_numbers: list[str]) -> Optional[int]:
    """Look up account id using AccountingMapping, then fallback to account_number."""
    from models import AccountingMapping, Account  # type: ignore

    mapping = (
        session.query(AccountingMapping)
        .filter_by(operation_type=operation_type, account_type=account_type, is_active=True)
        .first()
    )
    if mapping:
        return mapping.account_id

    for num in fallback_numbers:
        acc = session.query(Account).filter_by(account_number=str(num)).first()
        if acc:
            return acc.id
    return None


def _has_vat_line(lines, vat_account_id: int) -> bool:
    return any(l.account_id == vat_account_id for l in lines)


def _rebuild_balances(db, account_ids: set[int]) -> None:
    """Recompute stored balance_cash for a set of account IDs from the GL."""
    from models import Account, JournalEntryLine, JournalEntry  # type: ignore

    for acc_id in account_ids:
        acc = Account.query.get(acc_id)
        if not acc:
            continue
        # Sum all POSTED, non-deleted JE lines for this account
        lines = (
            db.session.query(JournalEntryLine)
            .join(JournalEntry, JournalEntry.id == JournalEntryLine.journal_entry_id)
            .filter(
                JournalEntryLine.account_id == acc_id,
                JournalEntry.is_deleted.isnot(True),
                JournalEntry.is_draft.isnot(True),
            )
            .all()
        )
        total_dr = sum((l.debit_cash or 0) for l in lines)
        total_cr = sum((l.credit_cash or 0) for l in lines)
        acc.balance_cash = round(total_dr - total_cr, 4)

    db.session.flush()


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Fix return invoice VAT split in JE")
    parser.add_argument("--apply", action="store_true", help="Commit changes (default is dry-run)")
    parser.add_argument("--start", default=None, help="Start date YYYY-MM-DD (inclusive)")
    parser.add_argument("--end",   default=None, help="End date YYYY-MM-DD (inclusive)")
    args = parser.parse_args()

    dry_run = not args.apply
    start_date = datetime.strptime(args.start, "%Y-%m-%d").date() if args.start else None
    end_date   = datetime.strptime(args.end,   "%Y-%m-%d").date() if args.end   else None

    print("=" * 70)
    print("fix_return_invoice_vat.py")
    print(f"  mode      : {'DRY-RUN (no changes)' if dry_run else '⚠️  APPLY — writes to DB'}")
    print(f"  date range: {start_date or 'all'} → {end_date or 'all'}")
    print("=" * 70)

    from app import app  # type: ignore

    with app.app_context():
        from models import db, Invoice, JournalEntry, JournalEntryLine  # type: ignore

        sess = db.session

        # ── resolve account IDs ──────────────────────────────────────────────
        vat_payable_id = _resolve_account(sess, 'بيع', 'vat_payable', ['2210', '2110'])
        vat_receivable_id = _resolve_account(
            sess, 'شراء من عميل', 'vat_receivable', ['1400', '1500']
        )
        sales_returns_id = _resolve_account(
            sess, 'مرتجع بيع', 'sales_returns', ['420', '400']
        )
        purchase_returns_id = _resolve_account(
            sess, 'مرتجع شراء', 'purchase_returns', ['513', '512', '511']
        )

        print(f"\nAccounts resolved:")
        print(f"  vat_payable      : {vat_payable_id}")
        print(f"  vat_receivable   : {vat_receivable_id}")
        print(f"  sales_returns    : {sales_returns_id}")
        print(f"  purchase_returns : {purchase_returns_id}")

        if not vat_payable_id or not vat_receivable_id:
            print("\n⛔  Could not resolve VAT accounts — check AccountingMapping or account_number.")
            return 1

        # ── query return invoices ────────────────────────────────────────────
        q = Invoice.query.filter(
            Invoice.invoice_type.in_(['مرتجع بيع', 'مرتجع شراء']),
            Invoice.total_tax > 0,
        )
        if start_date:
            q = q.filter(Invoice.invoice_date >= start_date)
        if end_date:
            q = q.filter(Invoice.invoice_date <= end_date)

        invoices = q.order_by(Invoice.id).all()
        print(f"\nReturn invoices with total_tax > 0: {len(invoices)}")

        if not invoices:
            print("Nothing to fix.")
            return 0

        fixed = 0
        skipped = 0
        affected_accounts: set[int] = set()

        for inv in invoices:
            tax = float(inv.total_tax)

            je = JournalEntry.query.filter_by(invoice_id=inv.id).first()
            if not je:
                print(f"  ⚠️  #{inv.id} [{inv.invoice_type}] — no JE found, skipping")
                skipped += 1
                continue

            lines = JournalEntryLine.query.filter_by(journal_entry_id=je.id).all()

            # ── مرتجع بيع ───────────────────────────────────────────────────
            if inv.invoice_type == 'مرتجع بيع':
                if _has_vat_line(lines, vat_payable_id):
                    print(f"  ✅ #{inv.id} مرتجع بيع — VAT line already present, skip")
                    skipped += 1
                    continue

                # find the DR sales_returns line to reduce
                sr_line = next(
                    (l for l in lines
                     if l.account_id == sales_returns_id and (l.debit_cash or 0) > 0),
                    None,
                )
                if not sr_line:
                    # try any line with debit_cash on any returns-ish account
                    # (in case sales_returns_id mapping differs)
                    print(
                        f"  ⚠️  #{inv.id} مرتجع بيع — no DR sales_returns line found "
                        f"(acc={sales_returns_id}), skipping"
                    )
                    skipped += 1
                    continue

                net = round((sr_line.debit_cash or 0) - tax, 2)
                if net < 0:
                    print(
                        f"  ⚠️  #{inv.id} مرتجع بيع — net would be negative "
                        f"(debit={sr_line.debit_cash}, tax={tax}), skipping"
                    )
                    skipped += 1
                    continue

                print(
                    f"  🔧 #{inv.id} مرتجع بيع  date={inv.invoice_date}  tax={tax:.2f}"
                    f"  DR sales_returns: {sr_line.debit_cash:.2f} → {net:.2f}"
                    f"  + DR vat_payable: {tax:.2f}"
                )

                if not dry_run:
                    sr_line.debit_cash = net
                    new_line = JournalEntryLine(
                        journal_entry_id=je.id,
                        account_id=vat_payable_id,
                        debit_cash=tax,
                        credit_cash=0,
                        debit_weight=0,
                        credit_weight=0,
                        description="عكس ضريبة القيمة المضافة - مرتجع بيع (إصلاح)",
                    )
                    sess.add(new_line)
                    affected_accounts.update([sales_returns_id, vat_payable_id])
                    fixed += 1

            # ── مرتجع شراء ──────────────────────────────────────────────────
            elif inv.invoice_type == 'مرتجع شراء':
                if _has_vat_line(lines, vat_receivable_id):
                    print(f"  ✅ #{inv.id} مرتجع شراء — VAT line already present, skip")
                    skipped += 1
                    continue

                # find the CR purchase_returns line to reduce
                pr_line = next(
                    (l for l in lines
                     if l.account_id == purchase_returns_id and (l.credit_cash or 0) > 0),
                    None,
                )
                if not pr_line:
                    print(
                        f"  ⚠️  #{inv.id} مرتجع شراء — no CR purchase_returns line found "
                        f"(acc={purchase_returns_id}), skipping"
                    )
                    skipped += 1
                    continue

                net = round((pr_line.credit_cash or 0) - tax, 2)
                if net < 0:
                    print(
                        f"  ⚠️  #{inv.id} مرتجع شراء — net would be negative "
                        f"(credit={pr_line.credit_cash}, tax={tax}), skipping"
                    )
                    skipped += 1
                    continue

                print(
                    f"  🔧 #{inv.id} مرتجع شراء date={inv.invoice_date}  tax={tax:.2f}"
                    f"  CR purchase_returns: {pr_line.credit_cash:.2f} → {net:.2f}"
                    f"  + CR vat_receivable: {tax:.2f}"
                )

                if not dry_run:
                    pr_line.credit_cash = net
                    new_line = JournalEntryLine(
                        journal_entry_id=je.id,
                        account_id=vat_receivable_id,
                        debit_cash=0,
                        credit_cash=tax,
                        debit_weight=0,
                        credit_weight=0,
                        description="عكس ضريبة القيمة المضافة - مرتجع شراء (إصلاح)",
                    )
                    sess.add(new_line)
                    affected_accounts.update([purchase_returns_id, vat_receivable_id])
                    fixed += 1

        # ── commit & rebuild ─────────────────────────────────────────────────
        print(f"\n{'─' * 70}")
        print(f"  Fixed  : {fixed}")
        print(f"  Skipped: {skipped}")

        if dry_run:
            print("\n[DRY-RUN] No changes committed.  Re-run with --apply to apply.")
        else:
            if affected_accounts:
                print(f"\nRebuilding balances for accounts: {affected_accounts}")
                _rebuild_balances(db, affected_accounts)
            db.session.commit()
            print(f"\n✅ Committed. {fixed} return invoice(s) fixed.")

        return 0


if __name__ == "__main__":
    sys.exit(main())
