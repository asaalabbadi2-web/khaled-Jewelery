"""
repair_supplier_account_groups.py
==================================
Repair production data: move supplier financial/memo accounts from
raw-gold group (22xx/722xx) to manufactured-gold group (21xx/721xx).

Strategy:
  For each supplier whose financial account sits under a 22xx parent:
  1. If a CORRECT 21xx account already exists for this supplier  →  use it
     as the canonical account and delete the orphaned 22xx account.
  2. If ONLY a 22xx account exists (no lines or zero lines)       →  re-parent it
     to 21xx group.
  3. If ONLY a 22xx account exists WITH journal lines              →  re-parent it
     (safest: keeps all history, just moves it to the right group).
  Same logic for weight/memo accounts (722xx → 721xx).

Run (dry-run first):
    cd backend && source venv/bin/activate
    python devtools/repair_supplier_account_groups.py --dry-run
    python devtools/repair_supplier_account_groups.py --apply
"""
from __future__ import annotations
import sys, os, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from models import db, Account, Supplier, JournalEntryLine

APPLY = '--apply' in sys.argv

def digits(v):
    return ''.join(c for c in str(v or '') if c.isdigit())

def section(title):
    print()
    print('=' * 65)
    print(title)
    print('=' * 65)

with app.app_context():
    accs = Account.query.all()
    by_id = {a.id: a for a in accs}
    by_num = {digits(a.account_number): a for a in accs}

    # Resolve preferred manufactured-gold category accounts
    mfg_fin_category = (
        by_num.get('2100') or by_num.get('210') or by_num.get('21')
    )
    mfg_memo_root = (
        by_num.get('7210') or by_num.get('72100') or by_num.get('721')
    )

    if not mfg_fin_category:
        print('ERROR: Cannot find 2100/210 manufactured-gold category. Aborting.')
        sys.exit(1)

    if not mfg_memo_root:
        print('ERROR: Cannot find 7210/72100/721 weight memo root. Aborting.')
        sys.exit(1)

    section(f"Target groups")
    print(f"  Financial category : {mfg_fin_category.account_number} — {mfg_fin_category.name}")
    print(f"  Weight memo root   : {mfg_memo_root.account_number} — {mfg_memo_root.name}")

    # Which account IDs are "raw-gold" parents
    raw_fin_ids  = {a.id for a in accs if digits(a.account_number).startswith('22')}
    raw_memo_ids = {a.id for a in accs if digits(a.account_number).startswith('722')}

    suppliers = Supplier.query.all()
    fin_fixed = 0
    memo_fixed = 0
    fin_skipped = 0
    memo_skipped = 0

    section('Scanning suppliers')
    for s in suppliers:
        fin  = by_id.get(s.account_id) if s.account_id else None
        memo_id = getattr(fin, 'memo_account_id', None) if fin else None
        memo = by_id.get(memo_id) if memo_id else None

        # --- Financial account ---
        if fin and fin.parent_id in raw_fin_ids:
            fin_lines = JournalEntryLine.query.filter_by(account_id=fin.id).count()
            old_parent_num = digits(getattr(by_id.get(fin.parent_id), 'account_number', '?'))

            # Check if a correct 21xx account already exists for this supplier
            correct_fin = Account.query.filter_by(
                name=fin.name,
                transaction_type='cash',
                parent_id=mfg_fin_category.id,
            ).first()

            if correct_fin and correct_fin.id != fin.id:
                # Duplicate: canonical exists under 2100, orphan exists under 2200
                if fin_lines == 0:
                    print(f"  [FIN] sup {s.id:3} {s.name[:30]} — DELETE orphan {fin.account_number} (0 lines), keep {correct_fin.account_number}")
                    if APPLY:
                        s.account_id = correct_fin.id
                        db.session.flush()
                        db.session.delete(fin)
                        db.session.flush()
                        fin_fixed += 1
                    else:
                        fin_fixed += 1  # count for dry-run
                else:
                    # Lines on the orphan AND a canonical exists → merge lines then delete orphan
                    print(f"  [FIN] sup {s.id:3} {s.name[:30]} — MERGE {fin_lines} lines from {fin.account_number} → {correct_fin.account_number}")
                    if APPLY:
                        JournalEntryLine.query.filter_by(account_id=fin.id).update({'account_id': correct_fin.id})
                        db.session.flush()
                        s.account_id = correct_fin.id
                        db.session.flush()
                        db.session.delete(fin)
                        db.session.flush()
                        fin_fixed += 1
                    else:
                        fin_fixed += 1
            else:
                # Only the wrong-group account exists → re-parent it to 2100
                print(f"  [FIN] sup {s.id:3} {s.name[:30]} — RE-PARENT {fin.account_number} "
                      f"{old_parent_num}→{mfg_fin_category.account_number} ({fin_lines} lines)")
                if APPLY:
                    fin.parent_id = mfg_fin_category.id
                    # Fix account_number prefix: replace 2200xxx → 2100xxx
                    old_num = digits(fin.account_number)
                    if old_num.startswith('2200'):
                        new_num = '2100' + old_num[4:]
                        if not by_num.get(new_num):
                            fin.account_number = new_num
                            by_num[new_num] = fin
                    db.session.flush()
                    fin_fixed += 1
                else:
                    fin_fixed += 1

        # --- Memo/weight account ---
        if memo and memo.parent_id in raw_memo_ids:
            memo_lines = JournalEntryLine.query.filter_by(account_id=memo.id).count()
            old_parent_num = digits(getattr(by_id.get(memo.parent_id), 'account_number', '?'))

            correct_memo = Account.query.filter_by(
                name=memo.name,
                tracks_weight=True,
                parent_id=mfg_memo_root.id,
            ).first()

            if correct_memo and correct_memo.id != memo.id:
                if memo_lines == 0:
                    print(f"  [MEM] sup {s.id:3} {s.name[:30]} — DELETE orphan {memo.account_number} (0 lines), keep {correct_memo.account_number}")
                    if APPLY:
                        # Re-link financial account → correct memo
                        if fin:
                            fin.memo_account_id = correct_memo.id
                            db.session.flush()
                        db.session.delete(memo)
                        db.session.flush()
                        memo_fixed += 1
                    else:
                        memo_fixed += 1
                else:
                    print(f"  [MEM] sup {s.id:3} {s.name[:30]} — MERGE {memo_lines} lines from {memo.account_number} → {correct_memo.account_number}")
                    if APPLY:
                        JournalEntryLine.query.filter_by(account_id=memo.id).update({'account_id': correct_memo.id})
                        db.session.flush()
                        if fin:
                            fin.memo_account_id = correct_memo.id
                            db.session.flush()
                        db.session.delete(memo)
                        db.session.flush()
                        memo_fixed += 1
                    else:
                        memo_fixed += 1
            else:
                # Re-parent memo to mfg_memo_root
                print(f"  [MEM] sup {s.id:3} {s.name[:30]} — RE-PARENT {memo.account_number} "
                      f"{old_parent_num}→{mfg_memo_root.account_number} ({memo_lines} lines)")
                if APPLY:
                    memo.parent_id = mfg_memo_root.id
                    old_num = digits(memo.account_number)
                    # Fix prefix: 7220xxx → 72100xxx (add extra digit) or just re-number
                    if old_num.startswith('7220') or old_num.startswith('72200'):
                        prefix = '72100'
                        suffix = old_num[4:] if old_num.startswith('7220') else old_num[5:]
                        new_num = prefix + suffix
                        if not by_num.get(new_num):
                            memo.account_number = new_num
                            by_num[new_num] = memo
                    db.session.flush()
                    memo_fixed += 1
                else:
                    memo_fixed += 1

    section('Summary')
    mode = 'APPLIED' if APPLY else 'DRY-RUN (use --apply to execute)'
    print(f"Mode    : {mode}")
    print(f"Financial accounts to fix : {fin_fixed}")
    print(f"Memo/weight accounts to fix: {memo_fixed}")

    if APPLY:
        db.session.commit()
        print()
        print('✅ All changes committed to database.')
        print('Restart the backend for changes to take effect.')
    else:
        print()
        print('Run with --apply to execute the above changes.')
