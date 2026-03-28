import sqlite3, os

db_path = os.path.expanduser("~/yasargold/app.db")
con = sqlite3.connect(db_path)
cur = con.cursor()

def q(sql, params=()):
    cur.execute(sql, params)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    return cols, rows

def show(title, sql, params=()):
    cols, rows = q(sql, params)
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    if not rows:
        print("  (empty)")
        return
    widths = [max(len(str(c)), max((len(str(r[i])) for r in rows), default=0)) for i, c in enumerate(cols)]
    fmt = "  " + "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*cols))
    print("  " + "  ".join("-"*w for w in widths))
    for r in rows:
        print(fmt.format(*[str(x) for x in r]))

show("LAST 3 INVOICES",
     "SELECT id, invoice_type, total, is_posted, status FROM invoice ORDER BY id DESC LIMIT 3")

show("VOUCHERS for invoice 6",
     "SELECT id, voucher_type, status, amount_cash, reference_type, reference_id, journal_entry_id FROM voucher WHERE reference_type='invoice' AND reference_id=6")

show("JEs linked to invoice 6 (ref_type=invoice)",
     "SELECT id, entry_number, is_posted, is_draft, reference_type, reference_id FROM journal_entry WHERE reference_type='invoice' AND reference_id=6")

show("JE lines for above",
     """SELECT jel.id, jel.journal_entry_id, jel.account_id, jel.cash_debit, jel.cash_credit
        FROM journal_entry_line jel
        JOIN journal_entry je ON je.id = jel.journal_entry_id
        WHERE je.reference_type='invoice' AND je.reference_id=6""")

show("JEs linked to VOUCHERS of invoice 6 (ref_type=voucher)",
     """SELECT je.id, je.entry_number, je.is_posted, je.is_draft, je.reference_type, je.reference_id
        FROM journal_entry je
        JOIN voucher v ON v.id = je.reference_id AND je.reference_type='voucher'
        WHERE v.reference_type='invoice' AND v.reference_id=6""")

show("JE lines for voucher JEs of invoice 6",
     """SELECT jel.id, jel.journal_entry_id, jel.account_id, jel.cash_debit, jel.cash_credit
        FROM journal_entry_line jel
        JOIN journal_entry je ON je.id = jel.journal_entry_id
        JOIN voucher v ON v.id = je.reference_id AND je.reference_type='voucher'
        WHERE v.reference_type='invoice' AND v.reference_id=6""")

show("SBTs WHERE invoice_id=6",
     "SELECT id, safe_box_id, direction, amount_cash, ref_type, ref_id, invoice_id FROM safe_box_transaction WHERE invoice_id=6")

show("LATEST 5 SBTs (by id)",
     "SELECT id, safe_box_id, direction, amount_cash, ref_type, ref_id, invoice_id FROM safe_box_transaction ORDER BY id DESC LIMIT 5")

# Also check safe_box accounts
show("SAFE BOXES (id + account_id)",
     "SELECT id, name, safe_type, account_id FROM safe_box ORDER BY id")

# show the invoice JE lines with account names
show("Invoice JE lines with account names",
     """SELECT jel.id, jel.account_id, a.name, jel.cash_debit, jel.cash_credit
        FROM journal_entry_line jel
        JOIN journal_entry je ON je.id = jel.journal_entry_id
        LEFT JOIN account a ON a.id = jel.account_id
        WHERE je.reference_type='invoice' AND je.reference_id=6""")

con.close()
