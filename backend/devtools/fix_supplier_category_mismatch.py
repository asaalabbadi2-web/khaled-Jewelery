"""
Migration: Fix supplier account_category_id pointing to raw-gold group (2200/220)
           → redirect to manufactured-gold group (2100/210).

Run once:
    cd backend && source venv/bin/activate && python devtools/fix_supplier_category_mismatch.py
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from models import db, Account, Supplier

def _digits_only(v):
    return ''.join(c for c in str(v or '') if c.isdigit())

with app.app_context():
    # Identify raw-gold category accounts (220 / 2200) and manufactured-gold (210 / 2100).
    raw_gold_accounts = {
        a.id: a for a in Account.query.all()
        if _digits_only(str(a.account_number)).startswith('22') or
           _digits_only(str(a.account_number)) in ('220', '2200')
    }

    manufactured_groups = {
        _digits_only(str(a.account_number)): a
        for a in Account.query.all()
        if _digits_only(str(a.account_number)) in ('2100', '210', '21')
    }

    # Preferred manufactured-gold posting group
    mfg_category = (
        manufactured_groups.get('2100') or
        manufactured_groups.get('210') or
        manufactured_groups.get('21')
    )
    if not mfg_category:
        print("ERROR: Cannot find manufactured-gold supplier group (2100/210). Aborting.")
        sys.exit(1)

    print(f"Manufactured gold category → id={mfg_category.id}  number={mfg_category.account_number}  name={mfg_category.name}")
    print()

    # Find suppliers whose account_category_id points to a raw-gold account.
    wrong_suppliers = [
        s for s in Supplier.query.all()
        if s.account_category_id and s.account_category_id in raw_gold_accounts
    ]

    if not wrong_suppliers:
        print("✅ No suppliers with raw-gold category found. Nothing to fix.")
        sys.exit(0)

    print(f"Found {len(wrong_suppliers)} supplier(s) with raw-gold category — fixing...")
    for s in wrong_suppliers:
        old_cat = raw_gold_accounts[s.account_category_id]
        print(f"  Supplier id={s.id:4}  name={s.name[:40]}  "
              f"old_category={old_cat.account_number}({old_cat.name[:20]}) "
              f"→ {mfg_category.account_number}({mfg_category.name[:20]})")
        s.account_category_id = mfg_category.id

    db.session.commit()
    print()
    print(f"✅ Fixed {len(wrong_suppliers)} supplier(s). account_category_id now points to {mfg_category.account_number}.")
    print()
    print("NOTE: Existing financial account records (account_id) are NOT moved.")
    print("      Their journal entry history is unchanged.")
    print("      Re-running ensure_supplier_accounts will now create new accounts")
    print("      under the correct manufactured-gold group (2100) if needed.")
