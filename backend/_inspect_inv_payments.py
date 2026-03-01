#!/usr/bin/env python3
"""Check how invoice payments are split between cash safe and bank account."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from models import db, Account, JournalEntryLine, JournalEntry, Invoice, InvoicePayment

with app.app_context():
    # Pick a specific invoice that has both cash + card: inv_id=197 (total=23750, card=1050)
    # And inv_id=46 (total=16850.01, card=11000)
    for inv_id in [197, 46, 124]:
        inv = Invoice.query.get(inv_id)
        print(f"\n{'='*60}")
        print(f"Invoice {inv_id}: total={inv.total} type={inv.invoice_type}")
        
        # Check payments
        payments = InvoicePayment.query.filter_by(invoice_id=inv_id).all()
        print(f"  Payments ({len(payments)}):")
        for p in payments:
            from models import PaymentMethod
            pm = PaymentMethod.query.get(p.payment_method_id) if p.payment_method_id else None
            pm_name = pm.name if pm else "?"
            print(f"    pm={pm_name} amount={p.amount}")
        
        # Check JE lines
        jes = JournalEntry.query.filter_by(reference_type='invoice', reference_id=inv_id).all()
        for je in jes:
            print(f"\n  JE #{je.id} ({je.entry_number}):")
            je_lines = JournalEntryLine.query.filter_by(journal_entry_id=je.id).all()
            for jl in je_lines:
                acct = Account.query.get(jl.account_id)
                acct_name = acct.name[:40] if acct else "?"
                cd = float(getattr(jl, 'cash_debit', 0) or 0)
                cc = float(getattr(jl, 'cash_credit', 0) or 0)
                desc = getattr(jl, 'description', '')
                if cd != 0 or cc != 0:
                    print(f"    [{jl.account_id}] {acct_name}: cash_debit={cd:.2f} cash_credit={cc:.2f}  ({desc})")

    # Now: count ALL lines on the bank account (including unposted)
    print(f"\n{'='*60}")
    print(f"Bank account 1279 - ALL JE lines (posted + unposted):")
    all_lines = JournalEntryLine.query.filter_by(account_id=1279).all()
    posted_sum = 0
    unposted_sum = 0
    for l in all_lines:
        cd = float(getattr(l, 'cash_debit', 0) or 0)
        je = l.journal_entry
        if je.is_posted:
            posted_sum += cd
        else:
            unposted_sum += cd
    print(f"  Total lines: {len(all_lines)}")
    print(f"  Posted cash_debit sum: {posted_sum:.2f}")
    print(f"  UNposted cash_debit sum: {unposted_sum:.2f}")
    print(f"  Grand total: {posted_sum + unposted_sum:.2f}")
    
    # Also check: is the statement endpoint using a different balance computation?
    # Check what the live_balances function returns
    try:
        from routes import live_balances_by_account_ids
        live = live_balances_by_account_ids([1279])
        print(f"\n  live_balances_by_account_ids: {live}")
    except Exception as e:
        print(f"  live_balances error: {e}")
