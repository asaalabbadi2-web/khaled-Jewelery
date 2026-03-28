import sqlite3, os
db = os.path.expanduser("~/yasargold/app.db")
con = sqlite3.connect(db)
cur = con.cursor()

cur.execute("SELECT id, safe_box_id, direction, amount_cash, ref_type, ref_id, invoice_id FROM safe_box_transaction WHERE ref_id=9")
print("SBTs ref_id=9:", cur.fetchall())

cur.execute("SELECT MAX(id) FROM safe_box_transaction")
print("Max SBT id:", cur.fetchone()[0])

cur.execute("SELECT id, voucher_type, status, amount_cash, reference_type, reference_id, journal_entry_id, notes FROM voucher WHERE id=9")
print("Voucher 9:", cur.fetchone())

cur.execute("SELECT id, account_id, cash_debit, cash_credit FROM journal_entry_line WHERE journal_entry_id=16")
print("JE16 lines:", cur.fetchall())

cur.execute("SELECT id, name, account_id FROM safe_box WHERE account_id=15")
print("SafeBox account_id=15:", cur.fetchall())

# Also check for ref_id=9 with any ref_type
cur.execute("SELECT * FROM safe_box_transaction WHERE ref_id=9 OR invoice_id=9")
print("SBTs ref_id=9 or invoice_id=9:", cur.fetchall())

con.close()
