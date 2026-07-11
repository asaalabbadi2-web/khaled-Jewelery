#!/usr/bin/env python3
"""Find where the 94 unposted bank JE lines come from."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from models import db, Account, JournalEntryLine, JournalEntry, Invoice

with app.app_context():
    # Get all unposted JE lines on bank account 1279
    unposted_lines = (JournalEntryLine.query
        .filter_by(account_id=1279)
        .join(JournalEntry)
        .filter(JournalEntry.is_posted == False)
        .all())
    
    print(f"Unposted JE lines on bank account: {len(unposted_lines)}")
    
    # Group by JE
    je_ids = set()
    inv_ids = set()
    total_amount = 0
    for l in unposted_lines:
        je = l.journal_entry
        je_ids.add(je.id)
        cd = float(getattr(l, 'cash_debit', 0) or 0)
        total_amount += cd
        if je.reference_type == 'invoice':
            inv_ids.add(je.reference_id)
    
    print(f"Unique JEs: {len(je_ids)}")
    print(f"Unique invoices: {len(inv_ids)}")
    print(f"Total unposted cash_debit: {total_amount:.2f}")
    
    # Check these invoices
    print(f"\nInvoice status for unposted JE invoices:")
    posted_inv = 0
    unposted_inv = 0
    for inv_id in sorted(inv_ids)[:20]:
        inv = Invoice.query.get(inv_id)
        if inv:
            status = "POSTED" if inv.is_posted else "UNPOSTED"
            if inv.is_posted:
                posted_inv += 1
            else:
                unposted_inv += 1
            # Find amount on bank for this invoice
            je = JournalEntry.query.filter_by(reference_type='invoice', reference_id=inv_id, is_posted=False).first()
            bank_line = JournalEntryLine.query.filter_by(journal_entry_id=je.id, account_id=1279).first() if je else None
            bank_amt = float(getattr(bank_line, 'cash_debit', 0) or 0) if bank_line else 0
            print(f"  inv_id={inv_id} {status} total={inv.total} bank_jel={bank_amt:.2f}")
    
    if len(inv_ids) > 20:
        print(f"  ... and {len(inv_ids) - 20} more")
    
    print(f"\nPosted invoices with unposted JEs: {posted_inv}")
    print(f"Unposted invoices with unposted JEs: {unposted_inv}")
    
    # KEY QUESTION: Are there duplicate JEs per invoice?
    # (Both a posted and unposted JE for the same invoice)
    print(f"\n=== Duplicate JE check ===")
    dupes = 0
    for inv_id in sorted(inv_ids):
        posted_jes = JournalEntry.query.filter_by(reference_type='invoice', reference_id=inv_id, is_posted=True).count()
        unposted_jes = JournalEntry.query.filter_by(reference_type='invoice', reference_id=inv_id, is_posted=False).count()
        if posted_jes > 0 and unposted_jes > 0:
            dupes += 1
            if dupes <= 5:
                print(f"  DUPE inv_id={inv_id}: {posted_jes} posted + {unposted_jes} unposted JEs")
    
    print(f"Total invoices with BOTH posted and unposted JEs: {dupes}")
    
    # Total JEs per invoice for the affected set
    total_jes_for_set = JournalEntry.query.filter(
        JournalEntry.reference_type == 'invoice',
        JournalEntry.reference_id.in_(list(inv_ids))
    ).count()
    print(f"Total JEs for affected {len(inv_ids)} invoices: {total_jes_for_set}")
