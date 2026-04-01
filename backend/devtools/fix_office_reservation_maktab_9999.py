"""
fix_office_reservation_maktab_9999.py
======================================
Repairs مكتب ٩٩٩٩ (supplier_id=31) accounting inconsistencies from
reservation RES-20260401205410-0046.

Problems fixed:
  1. Corrective JE: transfers ٢٨,٠٠٠ from wrong account 2100030 → 2100029
  2. Syncs stored balance_cash on accounts 2100029 and 2100030
  3. Closes reservation 46: paid_amount = 58,000, payment_status = 'paid'
  4. Syncs supplier 31 balance_cash = 0
  5. Soft-deletes the two zero-value lines in JE-151 (wrong supplier reference)

Usage:
    cd backend && source venv/bin/activate
    python devtools/fix_office_reservation_maktab_9999.py --dry-run
    python devtools/fix_office_reservation_maktab_9999.py --apply
"""
from __future__ import annotations
import sys, os, argparse
from datetime import datetime

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app import app
from models import db, Account, Supplier, JournalEntry, JournalEntryLine, OfficeReservation

APPLY = '--apply' in sys.argv

def header(title):
    print()
    print('=' * 70)
    print(f'  {title}')
    print('=' * 70)

def action(msg, extra=''):
    tag = '[APPLY]   ' if APPLY else '[DRY-RUN] '
    print(f'  {tag}{msg}', end='')
    if extra:
        print(f'  ← {extra}', end='')
    print()

with app.app_context():
    mode = 'APPLY MODE' if APPLY else 'DRY-RUN (pass --apply to commit changes)'
    print()
    print('╔' + '═' * 68 + '╗')
    print(f'║  fix_office_reservation_maktab_9999  —  {mode:<27}║')
    print('╚' + '═' * 68 + '╝')

    # ── Load accounts ──────────────────────────────────────────────────────
    acc_2100029 = Account.query.filter_by(account_number='2100029').first()
    acc_2100030 = Account.query.filter_by(account_number='2100030').first()

    if not acc_2100029 or not acc_2100030:
        print('\nERROR: Accounts 2100029 or 2100030 not found. Aborting.')
        sys.exit(1)

    supplier = Supplier.query.get(31)
    reservation = OfficeReservation.query.get(46)
    je_151 = JournalEntry.query.get(151)

    print(f'\n  Account 2100029  id={acc_2100029.id}  stored_cash={acc_2100029.balance_cash}')
    print(f'  Account 2100030  id={acc_2100030.id}  stored_cash={acc_2100030.balance_cash}')
    print(f'  Supplier 31      balance_cash={supplier.balance_cash if supplier else "NOT FOUND"}')
    print(f'  Reservation 46   paid_amount={reservation.paid_amount if reservation else "NOT FOUND"}  status={reservation.payment_status if reservation else ""}')
    print(f'  JE-151           id={je_151.id if je_151 else "NOT FOUND"}  lines={len(je_151.lines) if je_151 else 0}')

    # ── Verify live balances ───────────────────────────────────────────────
    from sqlalchemy import text as sqltxt
    def live_cash(account_id):
        row = db.session.execute(sqltxt("""
            SELECT COALESCE(SUM(jel.cash_debit),0) - COALESCE(SUM(jel.cash_credit),0)
            FROM journal_entry_line jel
            JOIN journal_entry je ON je.id = jel.journal_entry_id
            WHERE jel.account_id = :aid
              AND jel.is_deleted = 0
              AND je.is_deleted = 0
        """), {'aid': account_id}).fetchone()
        return round(row[0] or 0, 6)

    live_2100029 = live_cash(acc_2100029.id)
    live_2100030 = live_cash(acc_2100030.id)
    print(f'\n  Live 2100029 = {live_2100029}  (should be -28,000 before fix)')
    print(f'  Live 2100030 = {live_2100030}  (should be +28,000 before fix)')

    if abs(live_2100029 - (-28000.0)) > 1 or abs(live_2100030 - 28000.0) > 1:
        print('\n  WARNING: Live balances differ from expected. Script may have already run '
              'or data has changed. Verify before applying.')
        if APPLY:
            print('  Aborting to prevent double-correction.')
            sys.exit(1)

    # ── FIX 1: Corrective journal entry ────────────────────────────────────
    header('FIX 1 — Corrective JE: move 28,000 from 2100030 → 2100029')
    action('Create JE: Dr 2100029 28,000 | Cr 2100030 28,000')

    if APPLY:
        je = JournalEntry(
            date=datetime.now(),
            description='تسوية تصحيحية: نقل دفعة ٢٨,٠٠٠ من حساب المورد إلى حساب المكتب (مكتب ٩٩٩٩)',
            entry_type='عادي',
            reference_type='correction',
            created_by='fix_script',
            is_draft=False,
            is_posted=True,
            posted_at=datetime.now(),
            posted_by='fix_script',
        )
        db.session.add(je)
        db.session.flush()  # get je.id

        line_dr = JournalEntryLine(
            journal_entry_id=je.id,
            account_id=acc_2100029.id,
            supplier_id=31,
            cash_debit=28000.0,
            cash_credit=0.0,
            description='تسوية: إغلاق رصيد المكتب (عيار 24 - الدفعة المتبقية)',
            is_deleted=False,
        )
        line_cr = JournalEntryLine(
            journal_entry_id=je.id,
            account_id=acc_2100030.id,
            supplier_id=31,
            cash_debit=0.0,
            cash_credit=28000.0,
            description='تسوية: عكس الدفعة المرحّلة للحساب الخاطئ',
            is_deleted=False,
        )
        db.session.add(line_dr)
        db.session.add(line_cr)
        db.session.flush()
        print(f'    → Created JE id={je.id}  {je.entry_number}')

    # ── FIX 2: Sync stored balance_cash ───────────────────────────────────
    header('FIX 2 — Sync stored balance_cash')
    action(f'Set 2100029.balance_cash = 0.0', f'was {acc_2100029.balance_cash}')
    action(f'Set 2100030.balance_cash = 0.0', f'was {acc_2100030.balance_cash}')

    if APPLY:
        acc_2100029.balance_cash = 0.0
        acc_2100030.balance_cash = 0.0

    # ── FIX 3: Close reservation ───────────────────────────────────────────
    header('FIX 3 — Close reservation 46')
    if reservation:
        action(f'Set paid_amount = 58000.0', f'was {reservation.paid_amount}')
        action(f'Set payment_status = paid', f'was {reservation.payment_status}')
        if APPLY:
            reservation.paid_amount = 58000.0
            reservation.payment_status = 'paid'
    else:
        print('  SKIP: reservation 46 not found')

    # ── FIX 4: Sync supplier balance ───────────────────────────────────────
    header('FIX 4 — Sync supplier 31 balance_cash')
    if supplier:
        action(f'Set balance_cash = 0.0', f'was {supplier.balance_cash}')
        if APPLY:
            supplier.balance_cash = 0.0
    else:
        print('  SKIP: supplier 31 not found')

    # ── FIX 5: Soft-delete zero lines in JE-151 ───────────────────────────
    header('FIX 5 — Soft-delete zero-value lines in JE-151')
    if je_151:
        for line in je_151.lines:
            total = (line.cash_debit + line.cash_credit +
                     line.debit_21k + line.credit_21k +
                     (line.debit_weight or 0) + (line.credit_weight or 0))
            if abs(total) < 0.001 and not line.is_deleted:
                action(f'Soft-delete JEL id={line.id}  account_id={line.account_id}')
                if APPLY:
                    line.is_deleted = True
                    line.deleted_at = datetime.now()
    else:
        print('  SKIP: JE-151 not found')

    # ── Commit ─────────────────────────────────────────────────────────────
    if APPLY:
        db.session.commit()
        print()
        print('  ✅  All fixes committed successfully.')
    else:
        print()
        print('  ℹ️   Dry-run complete. No changes were made.')
        print('  ℹ️   Run with --apply to commit.')
