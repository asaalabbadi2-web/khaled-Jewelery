#!/usr/bin/env python3
"""Check what the 94 unposted JEs on bank account actually are."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from models import db, JournalEntryLine, JournalEntry

with app.app_context():
    unposted_lines = (JournalEntryLine.query
        .filter_by(account_id=1279)
        .join(JournalEntry)
        .filter(JournalEntry.is_posted == False)
        .all())
    
    print(f"Unposted JE lines on bank: {len(unposted_lines)}")
    
    # Check the JE details
    seen_jes = set()
    for l in unposted_lines[:10]:
        je = l.journal_entry
        if je.id in seen_jes:
            continue
        seen_jes.add(je.id)
        cd = float(getattr(l, 'cash_debit', 0) or 0)
        print(f"  JE id={je.id} num={je.entry_number} date={je.date} type={je.entry_type}")
        print(f"    ref_type={je.reference_type} ref_id={je.reference_id} ref_num={je.reference_number}")
        print(f"    is_draft={je.is_draft} is_posted={je.is_posted} is_deleted={je.is_deleted}")
        print(f"    desc={je.description}")
        print(f"    bank_cash_debit={cd:.2f}")
        print()
    
    # Count by reference_type
    from collections import Counter
    ref_types = Counter()
    for l in unposted_lines:
        je = l.journal_entry
        ref_types[je.reference_type or 'NULL'] += 1
    print(f"By reference_type: {dict(ref_types)}")
    
    # Count by entry_type
    entry_types = Counter()
    for l in unposted_lines:
        je = l.journal_entry
        entry_types[je.entry_type or 'NULL'] += 1
    print(f"By entry_type: {dict(entry_types)}")
    
    # Check is_draft values
    drafts = sum(1 for l in unposted_lines if l.journal_entry.is_draft)
    non_drafts = len(unposted_lines) - drafts
    print(f"is_draft=True: {drafts}, is_draft=False: {non_drafts}")
