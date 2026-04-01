"""
cleanup_orphan_2200_accounts.py
================================
Delete orphaned accounts that are still numbered 22xx/722xx but have:
  - 0 journal lines
  - 0 child accounts
  - No supplier pointing to them as account_id

These are left-over after repair_supplier_account_groups.py:
accounts whose number couldn't be renamed (canonical already existed).

Run:
    python devtools/cleanup_orphan_2200_accounts.py --dry-run
    python devtools/cleanup_orphan_2200_accounts.py --apply
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

APPLY = '--apply' in sys.argv

from app import app
from models import db, Account, Supplier, Customer, JournalEntryLine, SafeBox

def digits(v):
    return ''.join(c for c in str(v or '') if c.isdigit())

with app.app_context():
    accs = Account.query.all()
    by_id = {a.id: a for a in accs}

    # Accounts used by suppliers / customers / safe boxes
    supplier_fin_ids = {s.account_id for s in Supplier.query.all() if s.account_id}
    supplier_cat_ids = {s.account_category_id for s in Supplier.query.all() if s.account_category_id}
    customer_ids     = set()
    safe_ids = {sb.account_id for sb in SafeBox.query.all() if sb.account_id}

    all_protected = supplier_fin_ids | supplier_cat_ids | customer_ids | safe_ids

    # Children by parent_id
    children = {}
    for a in accs:
        if a.parent_id:
            children.setdefault(a.parent_id, []).append(a.id)

    candidates = []
    for a in accs:
        num = digits(a.account_number)
        # Only 22xx or 722xx accounts (that shouldn't hold supplier data)
        is_raw_fin = num.startswith('22') and not num.startswith('221')  # exclude 221x (VAT)
        is_raw_memo = num.startswith('722')

        if not (is_raw_fin or is_raw_memo):
            continue

        # Skip root group accounts (2200, 220, 72200, 7220)
        if num in ('22', '220', '2200', '72', '721', '7210', '722', '7220', '72200', '72100'):
            continue

        # Skip if protected (linked to a supplier/customer/safe)
        if a.id in all_protected:
            continue

        # Skip if has children
        if a.id in children:
            continue

        # Skip if has journal lines
        line_count = JournalEntryLine.query.filter_by(account_id=a.id).count()
        if line_count > 0:
            continue

        candidates.append(a)

    print(f"Orphaned accounts safe to delete: {len(candidates)}")
    print()
    for a in sorted(candidates, key=lambda x: x.account_number):
        parent = by_id.get(a.parent_id)
        pnum = getattr(parent, 'account_number', '?')
        print(f"  DELETE {a.account_number:12} id={a.id:5} (parent:{pnum}) — {a.name[:50]}")

    if APPLY:
        for a in candidates:
            db.session.delete(a)
        db.session.commit()
        print()
        print(f"✅ Deleted {len(candidates)} orphaned accounts.")
    else:
        print()
        print("Run with --apply to delete the above accounts.")
