"""
fix_production_supplier_accounts.py
=====================================
Production repair script: fixes supplier accounts that were incorrectly
created under the raw-gold group (22xx / 722xx) instead of the
manufactured-gold group (21xx / 721xx).

Runs in 3 phases:
  Phase 1 — Fix supplier.account_category_id (pointer to parent group)
  Phase 2 — Re-parent existing financial/memo accounts from 22xx → 21xx
  Phase 3 — Delete empty orphan accounts left under 22xx

Compatible with SQLite (development) and PostgreSQL (production).
Safe to run multiple times (idempotent).

Usage (via Docker on production):
    docker exec yasargold-backend python devtools/fix_production_supplier_accounts.py --dry-run
    docker exec yasargold-backend python devtools/fix_production_supplier_accounts.py --apply

Usage (local):
    cd backend && source venv/bin/activate
    python devtools/fix_production_supplier_accounts.py --dry-run
    python devtools/fix_production_supplier_accounts.py --apply
"""
from __future__ import annotations
import sys, os, argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from models import db, Account, Supplier, JournalEntryLine, SafeBox, Office

APPLY = '--apply' in sys.argv

# ──────────────────────────────────────────────
def digits(v):
    return ''.join(c for c in str(v or '') if c.isdigit())

def header(title):
    print()
    print('=' * 70)
    print(f'  {title}')
    print('=' * 70)

def action(msg):
    prefix = '  [APPLY]' if APPLY else '  [DRY-RUN]'
    print(f'{prefix} {msg}')

# ──────────────────────────────────────────────
with app.app_context():

    mode_label = 'APPLY MODE' if APPLY else 'DRY-RUN (pass --apply to execute changes)'
    print()
    print('╔' + '═' * 68 + '╗')
    print(f'║  fix_production_supplier_accounts.py  —  {mode_label:<25}║')
    print('╚' + '═' * 68 + '╝')

    accs    = Account.query.all()
    by_id   = {a.id: a for a in accs}
    by_num  = {digits(a.account_number): a for a in accs}

    # ── Resolve target groups ──────────────────
    mfg_fin = (
        by_num.get('2100') or by_num.get('210') or by_num.get('21')
    )
    mfg_memo = (
        by_num.get('7210') or by_num.get('72100') or by_num.get('721')
    )

    if not mfg_fin:
        print('\nERROR: Cannot find manufactured-gold financial group (2100/210). Aborting.')
        sys.exit(1)
    if not mfg_memo:
        print('\nERROR: Cannot find manufactured-gold weight group (7210/72100). Aborting.')
        sys.exit(1)

    print(f'\n  Financial target : {mfg_fin.account_number}  —  {mfg_fin.name}')
    print(f'  Weight target    : {mfg_memo.account_number}  —  {mfg_memo.name}')

    raw_fin_ids  = {a.id for a in accs if digits(a.account_number).startswith('22')
                    and not digits(a.account_number).startswith('221')}
    raw_memo_ids = {a.id for a in accs if digits(a.account_number).startswith('722')}

    total_changes = 0

    # ════════════════════════════════════════════
    header('PHASE 0 — Fix office accounts: transaction_type=both → cash')
    # ════════════════════════════════════════════
    # Office accounts created before this fix have transaction_type='both' and
    # tracks_weight=True.  ensure_supplier_accounts() rejects any account that
    # is not purely cash, which caused it to silently create a SECOND posting
    # account for each office-supplier, resulting in split balances.
    # Fix: normalise to cash/False; weight always lives in the memo (72xxxxx) account.
    offices = Office.query.all()
    phase0 = 0
    for o in offices:
        if not o.account_category_id:
            continue
        acc = by_id.get(o.account_category_id)
        if not acc:
            continue
        needs_fix = (
            getattr(acc, 'transaction_type', None) != 'cash'
            or bool(getattr(acc, 'tracks_weight', False))
        )
        if needs_fix:
            action(f'office {o.id:3}  {o.name[:40]}  |  '
                   f'acc {acc.account_number}  type={acc.transaction_type}  '
                   f'tracks_weight={acc.tracks_weight}  →  cash / False')
            if APPLY:
                acc.transaction_type = 'cash'
                acc.tracks_weight = False
                db.session.add(acc)
            phase0 += 1

    if APPLY and phase0:
        db.session.flush()
        # Refresh by_id after changes
        for o in offices:
            if o.account_category_id and o.account_category_id in by_id:
                by_id[o.account_category_id] = Account.query.get(o.account_category_id)

    print(f'\n  → {phase0} office account(s) to fix in Phase 0')
    total_changes += phase0

    # ════════════════════════════════════════════
    header('PHASE 1 — Fix supplier.account_category_id')
    # ════════════════════════════════════════════
    suppliers = Supplier.query.all()
    phase1 = 0
    for s in suppliers:
        if s.account_category_id and s.account_category_id in raw_fin_ids:
            old = by_id.get(s.account_category_id)
            action(f'sup {s.id:3}  {s.name[:40]}  |  '
                   f'category: {getattr(old,"account_number","?")} → {mfg_fin.account_number}')
            if APPLY:
                s.account_category_id = mfg_fin.id
            phase1 += 1

    print(f'\n  → {phase1} supplier(s) to fix in Phase 1')
    total_changes += phase1

    # ════════════════════════════════════════════
    header('PHASE 2 — Re-parent financial + weight accounts')
    # ════════════════════════════════════════════
    # Reload suppliers after potential phase-1 flush
    if APPLY and phase1:
        db.session.flush()

    suppliers = Supplier.query.all()
    phase2_fin = 0
    phase2_memo = 0

    for s in suppliers:
        fin  = by_id.get(s.account_id) if s.account_id else None
        memo_id  = getattr(fin, 'memo_account_id', None) if fin else None
        memo = by_id.get(memo_id) if memo_id else None

        # — Financial account —
        if fin and fin.parent_id in raw_fin_ids:
            fin_lines = JournalEntryLine.query.filter_by(account_id=fin.id).count()
            old_parent = by_id.get(fin.parent_id)

            # Check if a correct account (same name, under 2100) already exists
            correct = Account.query.filter_by(
                name=fin.name, transaction_type='cash', parent_id=mfg_fin.id
            ).first()

            if correct and correct.id != fin.id:
                if fin_lines == 0:
                    action(f'[FIN] sup {s.id:3} {s.name[:32]}  '
                           f'DELETE orphan {fin.account_number} (0 lines) → use {correct.account_number}')
                    if APPLY:
                        s.account_id = correct.id
                        db.session.flush()
                        db.session.delete(fin)
                        db.session.flush()
                        by_id.pop(fin.id, None)
                else:
                    action(f'[FIN] sup {s.id:3} {s.name[:32]}  '
                           f'MERGE {fin_lines} lines: {fin.account_number} → {correct.account_number}')
                    if APPLY:
                        JournalEntryLine.query.filter_by(account_id=fin.id).update(
                            {'account_id': correct.id}, synchronize_session=False)
                        db.session.flush()
                        s.account_id = correct.id
                        db.session.flush()
                        db.session.delete(fin)
                        db.session.flush()
                        by_id.pop(fin.id, None)
            else:
                old_num = digits(fin.account_number)
                new_num = None
                if old_num.startswith('2200') and not by_num.get('2100' + old_num[4:]):
                    new_num = '2100' + old_num[4:]
                action(f'[FIN] sup {s.id:3} {s.name[:32]}  '
                       f'RE-PARENT {fin.account_number} ({fin_lines} lines)'
                       + (f' + renumber → {new_num}' if new_num else ''))
                if APPLY:
                    fin.parent_id = mfg_fin.id
                    if new_num:
                        fin.account_number = new_num
                        by_num[new_num] = fin
                    db.session.flush()
            phase2_fin += 1

        # — Memo / weight account —
        # Reload fin in case it was replaced above
        fin  = by_id.get(s.account_id) if s.account_id else None
        memo_id  = getattr(fin, 'memo_account_id', None) if fin else None
        memo = by_id.get(memo_id) if memo_id else None

        if memo and memo.parent_id in raw_memo_ids:
            memo_lines = JournalEntryLine.query.filter_by(account_id=memo.id).count()

            correct_m = Account.query.filter_by(
                name=memo.name, tracks_weight=True, parent_id=mfg_memo.id
            ).first()

            if correct_m and correct_m.id != memo.id:
                if memo_lines == 0:
                    action(f'[MEM] sup {s.id:3} {s.name[:32]}  '
                           f'DELETE orphan {memo.account_number} (0 lines) → use {correct_m.account_number}')
                    if APPLY:
                        if fin:
                            fin.memo_account_id = correct_m.id
                            db.session.flush()
                        db.session.delete(memo)
                        db.session.flush()
                        by_id.pop(memo.id, None)
                else:
                    action(f'[MEM] sup {s.id:3} {s.name[:32]}  '
                           f'MERGE {memo_lines} lines: {memo.account_number} → {correct_m.account_number}')
                    if APPLY:
                        JournalEntryLine.query.filter_by(account_id=memo.id).update(
                            {'account_id': correct_m.id}, synchronize_session=False)
                        db.session.flush()
                        if fin:
                            fin.memo_account_id = correct_m.id
                            db.session.flush()
                        db.session.delete(memo)
                        db.session.flush()
                        by_id.pop(memo.id, None)
            else:
                old_num = digits(memo.account_number)
                new_num = None
                if old_num.startswith('7220') and not by_num.get('72100' + old_num[4:]):
                    new_num = '72100' + old_num[4:]
                elif old_num.startswith('72200') and not by_num.get('72100' + old_num[5:]):
                    new_num = '72100' + old_num[5:]
                action(f'[MEM] sup {s.id:3} {s.name[:32]}  '
                       f'RE-PARENT {memo.account_number} ({memo_lines} lines)'
                       + (f' + renumber → {new_num}' if new_num else ''))
                if APPLY:
                    memo.parent_id = mfg_memo.id
                    if new_num:
                        memo.account_number = new_num
                        by_num[new_num] = memo
                    db.session.flush()
            phase2_memo += 1

    print(f'\n  → {phase2_fin} financial account(s) and {phase2_memo} weight account(s) to fix in Phase 2')
    total_changes += phase2_fin + phase2_memo

    # ════════════════════════════════════════════
    header('PHASE 3 — Delete empty orphan accounts under 22xx/722xx')
    # ════════════════════════════════════════════
    if APPLY:
        db.session.flush()
        # Reload accounts after all changes
        accs   = Account.query.all()
        by_id  = {a.id: a for a in accs}
        by_num = {digits(a.account_number): a for a in accs}

    supplier_fin_ids = {s.account_id for s in Supplier.query.all() if s.account_id}
    supplier_cat_ids = {s.account_category_id for s in Supplier.query.all() if s.account_category_id}
    safe_ids         = {sb.account_id for sb in SafeBox.query.all() if sb.account_id}
    office_acc_ids   = {o.account_category_id for o in Office.query.all() if o.account_category_id}
    protected        = supplier_fin_ids | supplier_cat_ids | safe_ids | office_acc_ids

    children = {}
    for a in Account.query.all():
        if a.parent_id:
            children.setdefault(a.parent_id, []).append(a.id)

    # Root group accounts to preserve
    KEEP_ROOTS = {'22', '220', '2200', '722', '7220', '72200'}

    orphans = []
    for a in Account.query.all():
        num = digits(a.account_number)
        is_raw_fin  = num.startswith('22') and not num.startswith('221')
        is_raw_memo = num.startswith('722')
        if not (is_raw_fin or is_raw_memo):
            continue
        if num in KEEP_ROOTS:
            continue
        if a.id in protected:
            continue
        if a.id in children:
            continue
        line_count = JournalEntryLine.query.filter_by(account_id=a.id).count()
        if line_count > 0:
            print(f'  [SKIP] {a.account_number} — has {line_count} journal lines, NOT deleting')
            continue
        action(f'DELETE {a.account_number:12} id={a.id:5}  —  {a.name[:50]}')
        orphans.append(a)

    print(f'\n  → {len(orphans)} orphan account(s) to delete in Phase 3')
    total_changes += len(orphans)

    if APPLY:
        for a in orphans:
            db.session.delete(a)

    # ════════════════════════════════════════════
    header('PHASE 4 — Align supplier.account_id with office.account_category_id')
    # ════════════════════════════════════════════
    # When ensure_supplier_accounts() received a 'both' account it fell through and
    # created a separate cash account.  Now that Phase 0 corrected the account type
    # we must point supplier.account_id back to the office account and clean up the
    # orphan duplicate.
    if APPLY:
        db.session.flush()
        accs   = Account.query.all()
        by_id  = {a.id: a for a in accs}

    offices = Office.query.all()
    phase4_align  = 0
    phase4_delete = 0
    phase4_merge  = 0

    for o in offices:
        if not o.account_category_id or not o.supplier_id:
            continue
        supplier = Supplier.query.get(o.supplier_id)
        if not supplier:
            continue

        office_acc_id = int(o.account_category_id)
        sup_acc_id    = int(supplier.account_id) if supplier.account_id else None

        if sup_acc_id == office_acc_id:
            continue  # already aligned

        office_acc = by_id.get(office_acc_id)
        dup_acc    = by_id.get(sup_acc_id) if sup_acc_id else None

        if not office_acc:
            print(f'  [WARN] office {o.id} {o.name[:30]}: office account id={office_acc_id} not found, skip')
            continue

        # Count lines on the duplicate account
        dup_lines = JournalEntryLine.query.filter_by(account_id=sup_acc_id).count() if sup_acc_id else 0

        if dup_acc and dup_lines > 0:
            # Merge: move lines from duplicate to office account
            action(f'[ALN] office {o.id:3} {o.name[:30]}  '
                   f'MERGE {dup_lines} lines: {dup_acc.account_number} → {office_acc.account_number}')
            if APPLY:
                JournalEntryLine.query.filter_by(account_id=sup_acc_id).update(
                    {'account_id': office_acc_id}, synchronize_session=False)
                db.session.flush()
            phase4_merge += 1
        elif dup_acc:
            # Delete the empty duplicate
            action(f'[ALN] office {o.id:3} {o.name[:30]}  '
                   f'DELETE empty dup {dup_acc.account_number} (0 lines)')
            if APPLY:
                # Also delete its memo if it has one and it's empty
                dup_memo_id = getattr(dup_acc, 'memo_account_id', None)
                dup_memo = by_id.get(dup_memo_id) if dup_memo_id else None
                if dup_memo:
                    dup_memo_lines = JournalEntryLine.query.filter_by(account_id=dup_memo.id).count()
                    if dup_memo_lines == 0:
                        db.session.delete(dup_memo)
                        db.session.flush()
                        by_id.pop(dup_memo_id, None)
                db.session.delete(dup_acc)
                db.session.flush()
                by_id.pop(sup_acc_id, None)
            phase4_delete += 1

        # Point supplier to the office account
        action(f'[ALN] office {o.id:3} {o.name[:30]}  '
               f'supplier.account_id: {sup_acc_id} → {office_acc_id}')
        if APPLY:
            supplier.account_id = office_acc_id
            db.session.add(supplier)
            db.session.flush()
        phase4_align += 1

    print(f'\n  → {phase4_align} supplier(s) realigned, '
          f'{phase4_delete} empty dup(s) deleted, '
          f'{phase4_merge} dup(s) merged in Phase 4')
    total_changes += phase4_align + phase4_delete + phase4_merge

    # ════════════════════════════════════════════
    header('FINAL SUMMARY')
    # ════════════════════════════════════════════
    print(f'  Mode              : {mode_label}')
    print(f'  Phase 0 (office type): {phase0} account(s)')
    print(f'  Phase 1 (category): {phase1} supplier(s)')
    print(f'  Phase 2 fin       : {phase2_fin} account(s)')
    print(f'  Phase 2 memo      : {phase2_memo} account(s)')
    print(f'  Phase 3 (cleanup) : {len(orphans)} account(s)')
    print(f'  Phase 4 align     : {phase4_align} supplier(s), {phase4_delete} deleted, {phase4_merge} merged')
    print(f'  Total changes     : {total_changes}')

    if total_changes == 0:
        print()
        print('  ✅ Nothing to fix — production data is already clean.')
    elif APPLY:
        db.session.commit()
        print()
        print('  ✅ All changes committed successfully.')
        print('  ⚠️  Restart the backend container for caches to refresh:')
        print('     docker restart yasargold-backend')
    else:
        print()
        print('  ℹ️  Run with --apply to execute the above changes.')
