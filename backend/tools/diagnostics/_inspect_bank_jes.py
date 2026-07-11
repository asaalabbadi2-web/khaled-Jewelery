#!/usr/bin/env python3
"""Deep inspect JE lines on bank account to find the amount issue."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from models import db, Account, JournalEntryLine, JournalEntry

with app.app_context():
    # Bank account
    acc = Account.query.get(1279)
    print(f"Account: id={acc.id} num={acc.account_number} name={acc.name}")
    
    # Check all JE lines (first 5 in detail)
    lines = (JournalEntryLine.query
        .filter_by(account_id=1279)
        .join(JournalEntry)
        .filter(JournalEntry.is_posted == True)
        .order_by(JournalEntry.date)
        .all())
    
    print(f"Total posted JE lines: {len(lines)}")
    
    total_debit_cash = 0
    total_credit_cash = 0
    total_debit_gold = 0
    total_credit_gold = 0
    
    for i, l in enumerate(lines):
        dc = float(getattr(l, 'debit_cash', 0) or 0)
        cc = float(getattr(l, 'credit_cash', 0) or 0)
        dg = float(getattr(l, 'debit_gold', 0) or 0)
        cg = float(getattr(l, 'credit_gold', 0) or 0)
        total_debit_cash += dc
        total_credit_cash += cc
        total_debit_gold += dg
        total_credit_gold += cg
        
        if i < 5:
            je = l.journal_entry
            print(f"\n  Line {i}: je_id={je.id} date={je.date} ref_type={je.reference_type} ref_id={je.reference_id}")
            print(f"    debit_cash={dc} credit_cash={cc} debit_gold={dg} credit_gold={cg}")
            # Print ALL columns
            for col in l.__table__.columns:
                val = getattr(l, col.name, None)
                if val not in (None, 0, 0.0, '', False):
                    print(f"    {col.name} = {val}")
    
    print(f"\n=== TOTALS ===")
    print(f"debit_cash={total_debit_cash:.2f}  credit_cash={total_credit_cash:.2f}")
    print(f"debit_gold={total_debit_gold:.6f}  credit_gold={total_credit_gold:.6f}")
    print(f"net_cash={total_debit_cash - total_credit_cash:.2f}")
    
    # Also check: what does the system show as balance?
    print(f"\n=== Stored balance ===")
    print(f"balance_cash={getattr(acc, 'balance_cash', '?')}")
    print(f"balance_debit={getattr(acc, 'balance_debit', '?')}")
    print(f"balance_credit={getattr(acc, 'balance_credit', '?')}")
    
    # Check the first JE that references this account to see its full structure
    if lines:
        first_je = lines[0].journal_entry
        print(f"\n=== First JE detail (id={first_je.id}) ===")
        print(f"  entry_number={first_je.entry_number}")
        print(f"  description={first_je.description}")
        print(f"  entry_type={first_je.entry_type}")
        print(f"  reference_type={first_je.reference_type}")
        print(f"  reference_id={first_je.reference_id}")
        all_je_lines = JournalEntryLine.query.filter_by(journal_entry_id=first_je.id).all()
        for jl in all_je_lines:
            acct = Account.query.get(jl.account_id)
            acct_name = acct.name if acct else "?"
            print(f"  JEL: acct={jl.account_id}({acct_name}) dc={getattr(jl,'debit_cash',0)} cc={getattr(jl,'credit_cash',0)} dg={getattr(jl,'debit_gold',0)} cg={getattr(jl,'credit_gold',0)}")
