#!/usr/bin/env python3
"""Analyze payment patterns in Excel to diagnose card/network discrepancy."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from devtools.import_sales_invoices import (
    _read_xlsx_rows, _normalize_header, _parse_row, _group_invoices, _parse_number
)

raw_rows = _read_xlsx_rows("../SalesDB.xlsx")
fieldnames = [_normalize_header(h) for h in (raw_rows[0].keys() if raw_rows else [])]
print("HEADERS:", fieldnames[:20])
print()

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

# Analyze payment patterns
mixed_groups = 0
total_excel_card_max = 0.0
total_excel_card_sum = 0.0
total_excel_cash_max = 0.0
total_excel_cash_sum = 0.0
groups_with_card = 0

for gk, lines in sorted(grouped.items(), key=lambda x: (int(x[0]) if x[0].isdigit() else 0)):
    cash_vals = [ln.cash_amount for ln in lines]
    card_vals = [ln.card_amount for ln in lines]
    card_types = [ln.card_type for ln in lines]

    nonzero_card = [c for c in card_vals if c > 0]
    nonzero_cash = [c for c in cash_vals if c > 0]

    if nonzero_cash:
        total_excel_cash_max += max(nonzero_cash)
        total_excel_cash_sum += sum(nonzero_cash)

    if nonzero_card:
        groups_with_card += 1
        all_same = len(set(round(c, 2) for c in nonzero_card)) == 1
        card_max = max(nonzero_card)
        card_sum = sum(nonzero_card)
        total_excel_card_max += card_max
        total_excel_card_sum += card_sum

        if not all_same:
            mixed_groups += 1
            if mixed_groups <= 10:
                print(f"MIXED group {gk}: card_vals={card_vals}, card_types={card_types}")
                print(f"  max={card_max:.2f} sum={card_sum:.2f}")

print(f"\n=== Payment Analysis ===")
print(f"Groups with card: {groups_with_card}")
print(f"Groups with mixed card amounts: {mixed_groups}")
print(f"Total card (MAX method - what import uses): {total_excel_card_max:.2f}")
print(f"Total card (SUM method): {total_excel_card_sum:.2f}")
print(f"DIFF (SUM - MAX): {total_excel_card_sum - total_excel_card_max:.2f}")
print(f"\nTotal cash (MAX method): {total_excel_cash_max:.2f}")
print(f"Total cash (SUM method): {total_excel_cash_sum:.2f}")
print(f"DIFF cash (SUM - MAX): {total_excel_cash_sum - total_excel_cash_max:.2f}")

# Now check what the DB recorded
print("\n=== DB Bank Account Check ===")
from app import app
from models import db, Account, JournalEntryLine, JournalEntry
with app.app_context():
    # Find bank/network payment method accounts
    from models import PaymentMethod
    pms = PaymentMethod.query.filter_by(is_active=True).all()
    for pm in pms:
        acct_id = getattr(pm, 'account_id', None)
        acct_name = ""
        if acct_id:
            acct = Account.query.get(acct_id)
            acct_name = acct.name if acct else "?"
        print(f"  PM id={pm.id} name={pm.name} type={getattr(pm,'payment_type','')} account_id={acct_id} -> {acct_name}")

    # Check Riyad Bank account balance
    riyad = Account.query.filter(Account.name.contains("الرياض")).all()
    for acc in riyad:
        print(f"\n  Riyad bank account: id={acc.id} num={acc.account_number} name={acc.name}")
        # Sum JE lines
        lines = JournalEntryLine.query.filter_by(account_id=acc.id).join(JournalEntry).filter(JournalEntry.is_posted == True).all()
        total_debit = sum(float(getattr(l, 'debit_cash', 0) or 0) for l in lines)
        total_credit = sum(float(getattr(l, 'credit_cash', 0) or 0) for l in lines)
        print(f"  Posted JE lines: {len(lines)}, debit_cash={total_debit:.2f}, credit_cash={total_credit:.2f}, net={total_debit-total_credit:.2f}")
