#!/usr/bin/env python3
"""Sum actual cash_debit/cash_credit on bank account JE lines."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from models import db, Account, JournalEntryLine, JournalEntry

with app.app_context():
    lines = (JournalEntryLine.query
        .filter_by(account_id=1279)
        .join(JournalEntry)
        .filter(JournalEntry.is_posted == True)
        .order_by(JournalEntry.date)
        .all())

    total_cash_debit = 0
    total_cash_credit = 0
    
    for l in lines:
        cd = float(getattr(l, 'cash_debit', 0) or 0)
        cc = float(getattr(l, 'cash_credit', 0) or 0)
        total_cash_debit += cd
        total_cash_credit += cc
    
    print(f"Bank account 1279 (بنك الرياض):")
    print(f"  Posted JE lines: {len(lines)}")
    print(f"  SUM cash_debit: {total_cash_debit:.2f}")
    print(f"  SUM cash_credit: {total_cash_credit:.2f}")
    print(f"  NET (debit-credit): {total_cash_debit - total_cash_credit:.2f}")
    print(f"  Stored balance_cash: {Account.query.get(1279).balance_cash}")
    
    # Now check: group by invoice to see per-invoice amounts vs Excel card amounts
    # Get the linked invoice IDs
    print(f"\n=== Per-invoice card amounts (first 10) ===")
    from models import Invoice
    je_to_inv = {}
    seen_invs = set()
    for l in lines:
        je = l.journal_entry
        inv_id = je.reference_id if je.reference_type == 'invoice' else None
        if inv_id and inv_id not in seen_invs:
            seen_invs.add(inv_id)
            cd = float(getattr(l, 'cash_debit', 0) or 0)
            inv = Invoice.query.get(inv_id)
            inv_total = float(inv.total or 0) if inv else 0
            print(f"  inv_id={inv_id} card_JEL_amount={cd:.2f} inv_total={inv_total:.2f}")
            if len(seen_invs) >= 15:
                break
    
    # Check ALL invoice totals vs card amounts
    print(f"\n=== Aggregate check ===")
    total_inv_total = 0
    total_card_jel = 0
    mismatch_count = 0
    
    inv_card_amounts = {}
    for l in lines:
        je = l.journal_entry
        inv_id = je.reference_id if je.reference_type == 'invoice' else None
        if inv_id:
            cd = float(getattr(l, 'cash_debit', 0) or 0)
            if inv_id not in inv_card_amounts:
                inv_card_amounts[inv_id] = 0
            inv_card_amounts[inv_id] += cd
    
    for inv_id, card_total in inv_card_amounts.items():
        total_card_jel += card_total
        inv = Invoice.query.get(inv_id)
        if inv:
            total_inv_total += float(inv.total or 0)
    
    print(f"  Unique invoices: {len(inv_card_amounts)}")
    print(f"  SUM card JEL amounts: {total_card_jel:.2f}")
    print(f"  SUM invoice totals: {total_inv_total:.2f}")
    
    # Now load Excel expected card amounts per invoice for comparison
    from devtools.import_sales_invoices import (
        _read_xlsx_rows, _normalize_header, _parse_row, _group_invoices
    )
    raw_rows = _read_xlsx_rows("../SalesDB.xlsx")
    fieldnames = [_normalize_header(h) for h in (raw_rows[0].keys() if raw_rows else [])]
    parsed = []
    last_date = None
    for rr in raw_rows:
        try:
            pr = _parse_row(rr, fieldnames)
            if pr:
                parsed.append(pr)
                last_date = pr.date
        except:
            if last_date:
                rr2 = dict(rr)
                rr2["التاريخ"] = last_date.strftime("%Y/%m/%d")
                try:
                    pr = _parse_row(rr2, fieldnames)
                    if pr: parsed.append(pr)
                except: pass
    
    grouped = _group_invoices(parsed)
    
    # For groups with card: check what invoice ID it maps to
    # We'll use date+total+employee to match
    excel_card_total = 0
    excel_inv_total_for_card = 0
    for gk, glines in grouped.items():
        nonzero_card = [ln.card_amount for ln in glines if ln.card_amount > 0]
        if nonzero_card:
            card_max = max(nonzero_card)
            excel_card_total += card_max
            inv_total = 0
            for ln in glines:
                inv_total = max(inv_total, ln.line_total)
            excel_inv_total_for_card += inv_total
    
    print(f"\n  Excel total card: {excel_card_total:.2f}")
    print(f"  Excel total invoice value (for card groups): {excel_inv_total_for_card:.2f}")
    print(f"\n  System bank JEL total: {total_card_jel:.2f}")
    print(f"  DIFF (system - excel): {total_card_jel - excel_card_total:.2f}")
