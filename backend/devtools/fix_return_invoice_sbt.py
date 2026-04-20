#!/usr/bin/env python3
"""Backfill missing Vouchers (سندات صرف) + SBTs for OLD مرتجع بيع invoices.

Problem
-------
Return invoices (مرتجع بيع) created before the shared payment processing
section was correctly wired did not get:
  1. A Voucher record (سند صرف) → no audit trail in the vouchers list
  2. A SafeBoxTransaction direction='out' → safe box cash balance is overstated

Note: NEW مرتجع بيع invoices automatically get Voucher + SBT via the shared
payment processing section in routes.py (same as بيع invoices).
This script only backfills OLD invoices that are missing both.

Fix (per invoice)
---
  1. Resolve the customer's financial account (AR subledger)
  2. Resolve safe box (from InvoicePayments → invoice.safe_box_id → fallback)
  3. Create Voucher (type='payment', status='approved')
  4. Create VoucherAccountLine ×2  (debit customer, credit safe)
  5. Create JournalEntry + 2 JournalEntryLines
  6. Create SafeBoxTransaction direction='out'

Usage (inside Docker container)
---------------------------------
# Dry-run (default):
    docker compose -f docker-compose.prod.yml exec backend \\
        python backend/devtools/fix_return_invoice_sbt.py

# Apply:
    docker compose -f docker-compose.prod.yml exec backend \\
        python backend/devtools/fix_return_invoice_sbt.py --apply

# Date range + apply:
    docker compose -f docker-compose.prod.yml exec backend \\
        python backend/devtools/fix_return_invoice_sbt.py --start 2025-01-01 --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill Vouchers/SBTs for مرتجع بيع")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--start", default=None, help="Start date YYYY-MM-DD (inclusive)")
    parser.add_argument("--end",   default=None, help="End date YYYY-MM-DD (inclusive)")
    args = parser.parse_args()

    dry_run = not args.apply
    start_date = datetime.strptime(args.start, "%Y-%m-%d").date() if args.start else None
    end_date   = datetime.strptime(args.end,   "%Y-%m-%d").date() if args.end   else None

    print("=" * 70)
    print("fix_return_invoice_sbt.py  — Voucher + SBT backfill for مرتجع بيع")
    print(f"  mode      : {'DRY-RUN (no changes)' if dry_run else '⚠️  APPLY — writes to DB'}")
    print(f"  date range: {start_date or 'all'} → {end_date or 'all'}")
    print("=" * 70)

    from app import app  # type: ignore

    with app.app_context():
        from models import (  # type: ignore
            db,
            Invoice, InvoicePayment,
            Customer,
            SafeBox, SafeBoxTransaction,
            Voucher, VoucherAccountLine,
            JournalEntry, JournalEntryLine,
            Settings,
        )
        from party_account_service import ensure_customer_accounts  # type: ignore

        # ── helpers ──────────────────────────────────────────────────────────

        def _fallback_sb_id():
            try:
                s = Settings.query.first()
                main = getattr(s, 'main_cash_safe_box_id', None) if s else None
                if main:
                    return int(main)
            except Exception:
                pass
            sb = SafeBox.query.filter_by(safe_type='cash', is_active=True).order_by(
                SafeBox.is_default.desc(), SafeBox.id.asc()
            ).first()
            return sb.id if sb else None

        def _cash_safe(sb_id):
            """Return sb_id, but redirect to fallback if the safe is a gold safe."""
            if not sb_id:
                return _fallback_sb_id()
            sb = SafeBox.query.get(sb_id)
            if sb and (sb.safe_type or '').lower() == 'gold':
                return _fallback_sb_id()
            return sb_id

        def _gen_voucher_number(year):
            pattern = f'PV-{year}-%'
            last = (
                Voucher.query
                .filter(Voucher.voucher_number.like(pattern))
                .order_by(Voucher.voucher_number.desc())
                .first()
            )
            seq = 0
            if last and last.voucher_number:
                try:
                    seq = int(last.voucher_number.split('-')[-1])
                except Exception:
                    seq = 0
            while True:
                seq += 1
                candidate = f'PV-{year}-{seq:05d}'
                if not Voucher.query.filter_by(voucher_number=candidate).first():
                    return candidate

        def _gen_je_number(year):
            pattern = f'JE-{year}-%'
            last = (
                JournalEntry.query
                .filter(JournalEntry.entry_number.like(pattern))
                .order_by(JournalEntry.entry_number.desc())
                .first()
            )
            seq = 0
            if last and last.entry_number:
                try:
                    seq = int(last.entry_number.split('-')[-1])
                except Exception:
                    seq = 0
            while True:
                seq += 1
                candidate = f'JE-{year}-{seq:05d}'
                if not JournalEntry.query.filter_by(entry_number=candidate).first():
                    return candidate

        def _get_payment_lines(inv, fb):
            """Return [(amount, safe_box_id)] for this invoice."""
            payments = InvoicePayment.query.filter_by(invoice_id=inv.id).all()
            if payments:
                lines = []
                for pm in payments:
                    amount = float(pm.amount or 0)
                    if amount <= 0:
                        continue
                    sb_id = None
                    # Try notes JSON
                    try:
                        notes = json.loads(pm.notes or '{}')
                        sb_id = notes.get('safe_box_id')
                    except Exception:
                        pass
                    # Try payment method default safe
                    if not sb_id and pm.payment_method_id:
                        try:
                            from models import PaymentMethod  # type: ignore
                            pm_obj = PaymentMethod.query.get(pm.payment_method_id)
                            if pm_obj:
                                sb_id = getattr(pm_obj, 'default_safe_box_id', None)
                        except Exception:
                            pass
                    # Invoice-level fallback
                    if not sb_id:
                        sb_id = getattr(inv, 'safe_box_id', None)
                    sb_id = _cash_safe(sb_id) or fb
                    if sb_id:
                        lines.append((round(amount, 2), int(sb_id)))
                if lines:
                    return lines
            # No payments recorded — use invoice.total as single lump sum
            amount = float(inv.total or 0)
            sb_id = _cash_safe(getattr(inv, 'safe_box_id', None)) or fb
            if amount > 0 and sb_id:
                return [(round(amount, 2), int(sb_id))]
            return []

        def _customer_fin_account_id(inv):
            if not inv.customer_id:
                return None
            try:
                customer = Customer.query.get(inv.customer_id)
                if not customer:
                    return None
                return int(ensure_customer_accounts(customer).financial.id)
            except Exception as exc:
                print(f"      ⚠️  customer account error: {exc}")
                return None

        # ── main loop ────────────────────────────────────────────────────────

        fallback = _fallback_sb_id()
        print(f"\nFallback cash safe box id: {fallback}\n")

        q = Invoice.query.filter(
            Invoice.invoice_type == 'مرتجع بيع',
            Invoice.total > 0,
        )
        if start_date:
            q = q.filter(Invoice.date >= start_date)
        if end_date:
            q = q.filter(Invoice.date <= end_date)

        invoices = q.order_by(Invoice.id).all()
        print(f"مرتجعات بيع found: {len(invoices)}")

        fixed = 0
        skipped = 0

        for inv in invoices:

            # ── idempotency ────────────────────────────────────────────────
            if SafeBoxTransaction.query.filter_by(invoice_id=inv.id, direction='out').first():
                print(f"  ✅ #{inv.id} — SBT already exists, skip")
                skipped += 1
                continue
            if Voucher.query.filter_by(
                reference_type='invoice', reference_id=inv.id, voucher_type='payment'
            ).first():
                print(f"  ✅ #{inv.id} — Voucher already exists, skip")
                skipped += 1
                continue

            # ── resolve data ───────────────────────────────────────────────
            payment_lines = _get_payment_lines(inv, fallback)
            if not payment_lines:
                print(f"  ⚠️  #{inv.id} — cannot resolve payment/safe, skip")
                skipped += 1
                continue

            party_account_id = _customer_fin_account_id(inv)
            if not party_account_id:
                print(f"  ⚠️  #{inv.id} — cannot resolve customer account, skip")
                skipped += 1
                continue

            total = sum(a for a, _ in payment_lines)
            inv_date = inv.date
            if inv_date and not isinstance(inv_date, datetime):
                inv_date = datetime.combine(inv_date, datetime.min.time())
            if not inv_date:
                inv_date = datetime.now()
            year = inv_date.year
            inv_num = getattr(inv, 'invoice_number', None) or str(inv.id)

            print(
                f"  🔧 #{inv.id}  date={inv.date}  total={total:.2f}"
                f"  party_acc={party_account_id}"
                f"  lines={payment_lines}"
            )

            if dry_run:
                continue

            # ── create Voucher + JE + SBT per payment line ────────────────
            for (pm_amount, sb_id) in payment_lines:
                sb_obj = SafeBox.query.get(sb_id)
                safe_account_id = getattr(sb_obj, 'account_id', None) if sb_obj else None
                if not safe_account_id:
                    print(f"      ⚠️  safe_box {sb_id} has no account_id, skipping line")
                    continue

                # 1. Voucher
                voucher_number = _gen_voucher_number(year)
                voucher = Voucher(
                    voucher_number=voucher_number,
                    voucher_type='payment',
                    date=inv_date,
                    party_type='customer',
                    customer_id=inv.customer_id,
                    supplier_id=None,
                    amount_cash=float(pm_amount),
                    amount_gold=0.0,
                    description=f"استرداد نقدي مرتجع بيع #{inv_num} (backfill)",
                    reference_type='invoice',
                    reference_id=int(inv.id),
                    reference_number=str(inv_num),
                    notes=json.dumps({
                        'source': 'invoice_return_refund_backfill',
                        'invoice_id': int(inv.id),
                    }, ensure_ascii=False),
                    created_by='fix_return_invoice_sbt',
                    status='pending',
                )
                db.session.add(voucher)
                db.session.flush()

                # 2. VoucherAccountLines
                db.session.add(VoucherAccountLine(
                    voucher_id=voucher.id,
                    account_id=int(party_account_id),
                    line_type='debit',
                    amount_type='cash',
                    amount=float(pm_amount),
                    description='تسوية ذمة عميل - مرتجع بيع (backfill)',
                ))
                db.session.add(VoucherAccountLine(
                    voucher_id=voucher.id,
                    account_id=int(safe_account_id),
                    line_type='credit',
                    amount_type='cash',
                    amount=float(pm_amount),
                    description='استرداد نقدي للعميل (backfill)',
                ))
                db.session.flush()

                # 3. JournalEntry
                je_number = _gen_je_number(year)
                je = JournalEntry(
                    entry_number=je_number,
                    date=inv_date,
                    description=f'دفعات مرتجع بيع #{inv_num} (backfill)',
                    reference_type='invoice_payments',
                    reference_id=int(inv.id),
                    reference_number=str(inv_num),
                    is_posted=True,
                    posted_at=datetime.now(),
                    posted_by='fix_return_invoice_sbt',
                    created_by='fix_return_invoice_sbt',
                )
                db.session.add(je)
                db.session.flush()

                db.session.add(JournalEntryLine(
                    journal_entry_id=je.id,
                    account_id=int(party_account_id),
                    cash_debit=float(pm_amount),
                    description=f'تسوية ذمم - سند #{voucher_number} (backfill)',
                ))
                db.session.add(JournalEntryLine(
                    journal_entry_id=je.id,
                    account_id=int(safe_account_id),
                    cash_credit=float(pm_amount),
                    description=f'صرف نقد - سند #{voucher_number} (backfill)',
                ))
                db.session.flush()

                # 4. Approve Voucher
                voucher.status = 'approved'
                voucher.approved_at = datetime.now()
                voucher.approved_by = 'fix_return_invoice_sbt'
                voucher.journal_entry_id = je.id
                db.session.flush()

                # 5. SafeBoxTransaction direction='out'
                db.session.add(SafeBoxTransaction(
                    safe_box_id=int(sb_id),
                    ref_type='voucher',
                    ref_id=voucher.id,
                    invoice_id=int(inv.id),
                    direction='out',
                    amount_cash=float(pm_amount),
                    notes=f'cash refund - sale return backfill #{voucher_number}',
                    created_by='fix_return_invoice_sbt',
                ))
                db.session.flush()

            fixed += 1

        print(f"\n{'─' * 70}")
        print(f"  Fixed  : {fixed}")
        print(f"  Skipped: {skipped}")

        if dry_run:
            print("\n[DRY-RUN] No changes committed. Re-run with --apply to apply.")
        else:
            db.session.commit()
            print(f"\n✅ Committed. {fixed} invoice(s) processed.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
