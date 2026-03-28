import sqlite3

con = sqlite3.connect("/Users/salehalabbadi/yasargold/app.db")
cur = con.cursor()

cur.execute("SELECT id, account_id FROM safe_box WHERE id=1")
sb = cur.fetchone()
acct_id = sb[1]

cur.execute("SELECT SUM(CASE WHEN direction='in' THEN amount_cash ELSE -amount_cash END) FROM safe_box_transaction WHERE safe_box_id=1")
sbt_total = cur.fetchone()[0] or 0

cur.execute("""
    SELECT SUM(CASE WHEN jl.entry_type='debit' THEN jl.amount_cash ELSE -jl.amount_cash END)
    FROM journal_entry_line jl
    JOIN journal_entry je ON jl.journal_entry_id = je.id
    WHERE jl.account_id = ? AND je.is_posted = 1
""", (acct_id,))
gl_total = cur.fetchone()[0] or 0

print(f"SBT total for SB1: {sbt_total:,.2f}")
print(f"GL total for account {acct_id}: {gl_total:,.2f}")
print(f"Diff (SBT - GL): {sbt_total - gl_total:,.2f}")

cur.execute("""
    SELECT ref_type, COUNT(*), SUM(CASE WHEN direction='in' THEN amount_cash ELSE -amount_cash END)
    FROM safe_box_transaction WHERE safe_box_id=1
    GROUP BY ref_type ORDER BY 3 DESC
""")
print("\nSBT breakdown by ref_type:")
for row in cur.fetchall():
    print(f"  {str(row[0]):<35} count={row[1]:>4} net={row[2]:>15,.2f}")

# Find SBTs whose voucher JE is NOT posted (potential GL gap)
cur.execute("""
    SELECT sbt.id, sbt.ref_type, sbt.ref_id, sbt.invoice_id, sbt.direction, sbt.amount_cash,
           v.id as voucher_id, je.is_posted, je.id as je_id
    FROM safe_box_transaction sbt
    LEFT JOIN vouchers v ON v.id = sbt.ref_id AND sbt.ref_type='voucher'
    LEFT JOIN journal_entry je ON je.reference_type='voucher' AND je.reference_id=v.id
    WHERE sbt.safe_box_id=1 AND sbt.ref_type='voucher'
    ORDER BY sbt.id
""")
rows = cur.fetchall()
print(f"\nSBTs with ref_type='voucher' for SB1 (total {len(rows)}):")
unposted = [r for r in rows if r[7] != 1]
print(f"  Unposted JEs: {len(unposted)}")
for r in unposted[:10]:
    print(f"  SBT#{r[0]} ref_id={r[2]} inv={r[3]} dir={r[4]} amt={r[5]:,.2f} je_id={r[8]} posted={r[7]}")

# invoice_payment ref_type where no matching JE line on account 15
cur.execute("""
    SELECT sbt.id, sbt.ref_id, sbt.invoice_id, sbt.direction, sbt.amount_cash
    FROM safe_box_transaction sbt
    WHERE sbt.safe_box_id=1 AND sbt.ref_type='invoice_payment'
    ORDER BY sbt.id
""")
ip_rows = cur.fetchall()
print(f"\nSBTs with ref_type='invoice_payment' for SB1 (total {len(ip_rows)}):")
# For each, check if there's a JE line
no_je_total = 0
for r in ip_rows:
    ip_id = r[1]
    # Try to find a JE line through the voucher linkage
    cur.execute("""
        SELECT v.id, je.is_posted FROM vouchers v
        JOIN journal_entry je ON je.reference_type='voucher' AND je.reference_id=v.id
        WHERE v.extra_data LIKE '%"invoice_payment_id": ' || ? || '%'
    """, (str(ip_id),))
    je_rows = cur.fetchall()
    if not je_rows:
        no_je_total += r[4] if r[3]=='in' else -r[4]  # amount_cash
print(f"  SBTs with no matching JE: net≈{no_je_total:,.2f}")

con.close()
