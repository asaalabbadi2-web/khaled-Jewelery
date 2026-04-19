#!/usr/bin/env python3
"""Fix weights for sales invoices imported from Excel where qty > 1.

Bug: The importer divided total_weight by quantity before sending to backend,
but the backend treats 'weight' as the total line weight (not per-item).
Result: InvoiceItem.weight stores weight/qty instead of total weight.

This script fixes ALL affected data:
  1. InvoiceItem.weight — multiply back by qty
  2. Invoice.total_weight — recalculate from corrected items
  3. JournalEntryLine debit/credit per-karat fields — scale proportionally
  4. SafeBoxTransaction weight fields — scale proportionally
  5. Account cached balances — full rebuild
  6. Customer cached balances — full rebuild
  7. InventoryCostingConfig — recompute

CategoryWeightMovement is NOT affected (it already multiplies weight * qty).

Usage (inside Docker container):
    # Dry-run (no changes):
    docker compose exec backend python backend/devtools/fix_imported_weights.py

    # Apply:
    docker compose exec backend python backend/devtools/fix_imported_weights.py --apply

    # With custom date range:
    docker compose exec backend python backend/devtools/fix_imported_weights.py --start 2025-12-13 --end 2026-03-05 --apply
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def main():
    parser = argparse.ArgumentParser(description="Fix imported invoice weights (qty>1 bug)")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default is dry-run)")
    parser.add_argument("--start", default="2025-12-13", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2026-03-05", help="End date inclusive (YYYY-MM-DD)")
    args = parser.parse_args()

    start_date = datetime.strptime(args.start, "%Y-%m-%d").date()
    end_date = datetime.strptime(args.end, "%Y-%m-%d").date()

    from app import create_app  # type: ignore
    app = create_app()

    with app.app_context():
        from models import (  # type: ignore
            db, Invoice, InvoiceItem, JournalEntry, JournalEntryLine,
            SafeBoxTransaction, Account, Customer,
        )

        print(f"{'=' * 65}")
        print(f"  Fix Imported Invoice Weights (qty > 1 bug)")
        print(f"  Mode: {'APPLY' if args.apply else 'DRY-RUN'}")
        print(f"  Date range: {start_date} to {end_date}")
        print(f"{'=' * 65}")
        print()

        # ─────────────────────────────────────────────────────────
        # 1. Find affected sales invoices in date range
        # ─────────────────────────────────────────────────────────
        invoices = (
            Invoice.query
            .filter(Invoice.invoice_type == 'بيع')
            .filter(Invoice.date >= datetime.combine(start_date, datetime.min.time()))
            .filter(Invoice.date <= datetime.combine(end_date, datetime.max.time()))
            .order_by(Invoice.date.asc(), Invoice.id.asc())
            .all()
        )

        print(f"Sales invoices in date range: {len(invoices)}")
        print()

        stats = {
            'invoices_fixed': 0,
            'items_fixed': 0,
            'weight_correction_grams': 0.0,
            'je_lines_fixed': 0,
            'sbt_fixed': 0,
        }

        affected_account_ids = set()

        for inv in invoices:
            items = InvoiceItem.query.filter_by(invoice_id=inv.id).all()
            affected_items = [
                it for it in items
                if (it.quantity or 1) > 1 and float(it.weight or 0) > 0
            ]

            if not affected_items:
                continue

            stats['invoices_fixed'] += 1
            inv_date = inv.date.strftime("%Y-%m-%d") if inv.date else "?"
            print(f"--- Invoice #{inv.id} (date={inv_date}, total={inv.total}) ---")

            # Build old and new gold_by_karat for JE/SBT correction
            old_gold_by_karat = defaultdict(float)
            new_gold_by_karat = defaultdict(float)

            for it in items:
                karat_key = str(int(float(it.karat or 21)))
                old_w = float(it.weight or 0)
                qty = int(it.quantity or 1)

                if qty > 1 and old_w > 0:
                    new_w = round(old_w * qty, 6)
                    correction = new_w - old_w
                    stats['weight_correction_grams'] += correction
                    stats['items_fixed'] += 1

                    print(f"  ITEM {it.id}: {it.name} k{karat_key} qty={qty}")
                    print(f"    weight: {old_w}g -> {new_w}g (+{round(correction, 3)}g)")

                    old_gold_by_karat[karat_key] += old_w
                    new_gold_by_karat[karat_key] += new_w

                    if args.apply:
                        it.weight = new_w
                else:
                    old_gold_by_karat[karat_key] += old_w
                    new_gold_by_karat[karat_key] += old_w

            # --- Recalculate Invoice.total_weight ---
            if args.apply:
                new_total_weight = round(sum(float(it.weight or 0) for it in items), 6)
            else:
                new_total_weight = 0.0
                for it in items:
                    w = float(it.weight or 0)
                    q = int(it.quantity or 1)
                    new_total_weight += (w * q) if (q > 1 and w > 0) else w
                new_total_weight = round(new_total_weight, 6)

            old_total_weight = float(inv.total_weight or 0)
            print(f"  total_weight: {old_total_weight}g -> {new_total_weight}g")

            if args.apply:
                inv.total_weight = new_total_weight

            # --- Fix JournalEntryLine gold weights ---
            je = JournalEntry.query.filter_by(invoice_id=inv.id).first()
            if je:
                fixed = _fix_je_lines(je, old_gold_by_karat, new_gold_by_karat,
                                       args.apply, affected_account_ids)
                stats['je_lines_fixed'] += fixed

            # --- Fix SafeBoxTransaction gold weights ---
            try:
                sbts = SafeBoxTransaction.query.filter_by(invoice_id=inv.id).all()
                for sbt in sbts:
                    if _fix_sbt(sbt, old_gold_by_karat, new_gold_by_karat, args.apply):
                        stats['sbt_fixed'] += 1
            except Exception as exc:
                print(f"  WARNING: SBT error: {exc}")

            print()

        # ─────────────────────────────────────────────────────────
        # Phase 2: Rebuild cached balances
        # ─────────────────────────────────────────────────────────
        print(f"{'=' * 65}")
        print(f"  Phase 2: Rebuild cached balances")
        print(f"{'=' * 65}")

        if args.apply and stats['invoices_fixed'] > 0:
            # Flush item/JE changes first
            db.session.flush()

            # 5. Rebuild ALL account balances from JE lines
            print("  Rebuilding all Account balances...")
            try:
                from routes import _rebuild_all_account_balances  # type: ignore
                result = _rebuild_all_account_balances()
                print(f"    Updated {result.get('updated_accounts', '?')} accounts")
            except Exception as exc:
                print(f"    WARNING: Account rebuild error: {exc}")
                print("    -> Run manually: POST /api/system/rebuild-account-balances")

            # 6. Rebuild Customer cached balances
            print("  Rebuilding Customer balances...")
            try:
                _rebuild_customer_balances_inline(db, Customer, JournalEntryLine, JournalEntry)
                print("    Done")
            except Exception as exc:
                print(f"    WARNING: Customer rebuild error: {exc}")

            # 7. Recompute InventoryCostingConfig
            print("  Recomputing inventory costing...")
            try:
                from routes import recompute_gold_costing  # type: ignore
                recompute_gold_costing()
                print("    Done")
            except Exception as exc:
                print(f"    INFO: Costing recompute skipped: {exc}")
                print("    -> Run manually: POST /api/gold-costing/recompute")
        elif not args.apply:
            print(f"  Will rebuild on --apply: Account balances, Customer balances, Inventory costing")
        else:
            print("  No invoices affected, skipping rebuild.")

        # ─────────────────────────────────────────────────────────
        # Summary
        # ─────────────────────────────────────────────────────────
        print()
        print(f"{'=' * 65}")
        print(f"  SUMMARY ({'APPLIED' if args.apply else 'DRY-RUN'})")
        print(f"{'=' * 65}")
        print(f"  Invoices affected:        {stats['invoices_fixed']}")
        print(f"  InvoiceItems fixed:       {stats['items_fixed']}")
        print(f"  Weight correction:        +{round(stats['weight_correction_grams'], 3)} grams")
        print(f"  JE lines fixed:           {stats['je_lines_fixed']}")
        print(f"  SafeBoxTxns fixed:        {stats['sbt_fixed']}")
        if args.apply and stats['invoices_fixed'] > 0:
            print(f"  Account balances:         rebuilt")
            print(f"  Customer balances:        rebuilt")
            print(f"  Inventory costing:        recomputed")
        print()

        if args.apply:
            try:
                db.session.commit()
                print("  ALL CHANGES COMMITTED TO DATABASE.")
            except Exception as exc:
                db.session.rollback()
                print(f"  COMMIT FAILED: {exc}")
                sys.exit(1)
        else:
            print("  No changes made. Run with --apply to fix.")
            print()
            print("  Command:")
            print("    docker compose exec backend python backend/devtools/fix_imported_weights.py --apply")


# ═══════════════════════════════════════════════════════════════
# Helper: Fix JournalEntryLine debit/credit karat fields
# ═══════════════════════════════════════════════════════════════

def _fix_je_lines(je, old_gold_by_karat, new_gold_by_karat, apply, affected_account_ids):
    """Scale JE line gold weight fields proportionally per karat."""
    from models import JournalEntryLine  # type: ignore

    lines = JournalEntryLine.query.filter_by(journal_entry_id=je.id).all()

    # Karat -> (debit_field, credit_field)
    KARAT_FIELDS = {
        '18': ('debit_18k', 'credit_18k'),
        '21': ('debit_21k', 'credit_21k'),
        '22': ('debit_22k', 'credit_22k'),
        '24': ('debit_24k', 'credit_24k'),
    }

    fixed_count = 0

    for line in lines:
        line_changed = False

        # Track which accounts are affected
        if line.account_id:
            affected_account_ids.add(int(line.account_id))

        # Fix debit/credit per-karat fields
        for karat_key, (debit_field, credit_field) in KARAT_FIELDS.items():
            old_total = old_gold_by_karat.get(karat_key, 0)
            new_total = new_gold_by_karat.get(karat_key, 0)

            if old_total <= 0 or abs(old_total - new_total) < 0.001:
                continue

            ratio = new_total / old_total

            for field in (debit_field, credit_field):
                old_val = float(getattr(line, field, 0) or 0)
                if old_val <= 0:
                    continue

                new_val = round(old_val * ratio, 6)
                if abs(new_val - old_val) >= 0.001:
                    side = 'debit' if 'debit' in field else 'credit'
                    print(f"    JE line {line.id} [{side} {karat_key}k]: {old_val} -> {new_val}")
                    line_changed = True
                    if apply:
                        setattr(line, field, new_val)

        # Fix debit_weight / credit_weight (memo equivalent weights)
        for memo_field in ('debit_weight', 'credit_weight'):
            old_memo = float(getattr(line, memo_field, 0) or 0)
            if old_memo <= 0:
                continue

            old_main = sum(
                old_gold_by_karat.get(k, 0) * (int(k) / 21.0)
                for k in old_gold_by_karat
            )
            new_main = sum(
                new_gold_by_karat.get(k, 0) * (int(k) / 21.0)
                for k in new_gold_by_karat
            )
            if old_main > 0 and abs(old_main - new_main) > 0.001:
                ratio = new_main / old_main
                new_memo = round(old_memo * ratio, 6)
                if abs(new_memo - old_memo) >= 0.001:
                    print(f"    JE line {line.id} [{memo_field}]: {old_memo} -> {new_memo}")
                    line_changed = True
                    if apply:
                        setattr(line, memo_field, new_memo)

        # Fix analytic_weight_24k / analytic_weight_main
        for analytic_field, karat_divisor in [('analytic_weight_24k', 24.0), ('analytic_weight_main', 21.0)]:
            old_val = getattr(line, analytic_field, None)
            if old_val is None:
                continue
            old_val = float(old_val)
            if abs(old_val) <= 0.001:
                continue

            old_equiv = sum(
                old_gold_by_karat.get(k, 0) * (int(k) / karat_divisor)
                for k in old_gold_by_karat
            )
            new_equiv = sum(
                new_gold_by_karat.get(k, 0) * (int(k) / karat_divisor)
                for k in new_gold_by_karat
            )
            if abs(old_equiv) > 0.001 and abs(old_equiv - new_equiv) > 0.001:
                ratio = new_equiv / old_equiv
                new_val = round(old_val * ratio, 6)
                if abs(new_val - old_val) >= 0.001:
                    print(f"    JE line {line.id} [{analytic_field}]: {old_val} -> {new_val}")
                    line_changed = True
                    if apply:
                        setattr(line, analytic_field, new_val)

        # Fix gold_weight_equiv (legacy field)
        old_gwe = float(getattr(line, 'gold_weight_equiv', 0) or 0)
        if old_gwe > 0:
            old_main = sum(old_gold_by_karat.get(k, 0) * (int(k) / 21.0) for k in old_gold_by_karat)
            new_main = sum(new_gold_by_karat.get(k, 0) * (int(k) / 21.0) for k in new_gold_by_karat)
            if old_main > 0 and abs(old_main - new_main) > 0.001:
                ratio = new_main / old_main
                new_gwe = round(old_gwe * ratio, 6)
                if abs(new_gwe - old_gwe) >= 0.001:
                    print(f"    JE line {line.id} [gold_weight_equiv]: {old_gwe} -> {new_gwe}")
                    line_changed = True
                    if apply:
                        line.gold_weight_equiv = new_gwe

        if line_changed:
            fixed_count += 1

    return fixed_count


# ═══════════════════════════════════════════════════════════════
# Helper: Fix SafeBoxTransaction weight fields
# ═══════════════════════════════════════════════════════════════

def _fix_sbt(sbt, old_gold_by_karat, new_gold_by_karat, apply):
    """Scale SafeBoxTransaction weight_*k fields proportionally."""
    KARAT_FIELDS = {
        '18': 'weight_18k',
        '21': 'weight_21k',
        '22': 'weight_22k',
        '24': 'weight_24k',
    }

    changed = False
    for karat_key, field in KARAT_FIELDS.items():
        old_val = float(getattr(sbt, field, 0) or 0)
        if old_val <= 0:
            continue

        old_total = old_gold_by_karat.get(karat_key, 0)
        new_total = new_gold_by_karat.get(karat_key, 0)

        if old_total <= 0 or abs(old_total - new_total) < 0.001:
            continue

        ratio = new_total / old_total
        new_val = round(old_val * ratio, 6)

        if abs(new_val - old_val) >= 0.001:
            print(f"    SBT {sbt.id} [{field}]: {old_val} -> {new_val}")
            changed = True
            if apply:
                setattr(sbt, field, new_val)

    return changed


# ═══════════════════════════════════════════════════════════════
# Helper: Rebuild Customer cached gold balances
# ═══════════════════════════════════════════════════════════════

def _rebuild_customer_balances_inline(db, Customer, JournalEntryLine, JournalEntry):
    """Rebuild Customer.balance_gold_*k from JournalEntryLines."""
    from sqlalchemy import func

    customers = Customer.query.filter(Customer.active == True).all()

    for customer in customers:
        if not customer.id:
            continue

        rows = (
            db.session.query(
                (func.coalesce(func.sum(JournalEntryLine.debit_18k), 0.0)
                 - func.coalesce(func.sum(JournalEntryLine.credit_18k), 0.0)).label('b18'),
                (func.coalesce(func.sum(JournalEntryLine.debit_21k), 0.0)
                 - func.coalesce(func.sum(JournalEntryLine.credit_21k), 0.0)).label('b21'),
                (func.coalesce(func.sum(JournalEntryLine.debit_22k), 0.0)
                 - func.coalesce(func.sum(JournalEntryLine.credit_22k), 0.0)).label('b22'),
                (func.coalesce(func.sum(JournalEntryLine.debit_24k), 0.0)
                 - func.coalesce(func.sum(JournalEntryLine.credit_24k), 0.0)).label('b24'),
                (func.coalesce(func.sum(JournalEntryLine.cash_debit), 0.0)
                 - func.coalesce(func.sum(JournalEntryLine.cash_credit), 0.0)).label('cash'),
            )
            .join(JournalEntry)
            .filter(
                JournalEntryLine.customer_id == customer.id,
                JournalEntry.is_deleted == False,
                JournalEntryLine.is_deleted == False,
            )
            .first()
        )

        if rows:
            customer.balance_gold_18k = float(rows.b18 or 0.0)
            customer.balance_gold_21k = float(rows.b21 or 0.0)
            customer.balance_gold_22k = float(rows.b22 or 0.0)
            customer.balance_gold_24k = float(rows.b24 or 0.0)
            customer.balance_cash = float(rows.cash or 0.0)


if __name__ == "__main__":
    main()
