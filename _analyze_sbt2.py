import sqlite3

DB = "/Users/salehalabbadi/yasargold/app.db"
con = sqlite3.connect(DB)
cur = con.cursor()

# Get SB1 info
cur.execute("SELECT id, account_id, name FROM safe_box WHERE id=1")
sb = cur.fetchone()
acct_id = sb[1]
print(f"SB1: id={sb[0]} account_id={acct_id} name={sb[2]}")

# SBT total for SB1
cur.execute("""
    SELECT SUM(CASE WHEN direction='in' THEN amount_cash ELSE -amount_cash END)
    FROM safe_box_transaction WHERE safe_box_id=1
""")
sbt_total = cur.fetchone()[0] or 0
print(f"SBT total for SB1: {sbt_total:,.2f}")

# GL total (posted journal lines for account)
cur.execute("""
    SELECT SUM(COALESCE(jl.cash_debit,0) - COALESCE(jl.cash_credit,0))
    FROM journal_entry_line jl
    JOIN journal_entry je ON jl.journal_entry_id = je.id
    WHERE jl.account_id = ? AND je.is_posted = 1 AND COALESCE(jl.is_deleted,0)=0
""", (acct_id,))
gl_total = cur.fetchone()[0] or 0
print(f"GL total for account {acct_id}: {gl_total:,.2f}")
print(f"Diff (SBT - GL): {sbt_total - gl_total:,.2f}")

# SBT breakdown by ref_type
cur.execute("""
    SELECT ref_type, COUNT(*), SUM(CASE WHEN direction='in' THEN amount_cash ELSE -amount_cash END)
    FROM safe_box_transaction WHERE safe_box_id=1
    GROUP BY ref_type ORDER BY 3 DESC
""")
print("\nSBT breakdown by ref_type (SB1):")
for row in cur.fetchall():
    print(f"  {str(row[0]):<35} count={row[1]:>4} net={row[2]:>15,.2f}")

# GL lines — breakdown by je reference_type
cur.execute("""
    SELECT je.reference_type, COUNT(*), SUM(COALESCE(jl.cash_debit,0) - COALESCE(jl.cash_credit,0))
    FROM journal_entry_line jl
    JOIN journal_entry je ON jl.journal_entry_id = je.id
    WHERE jl.account_id = ? AND je.is_posted = 1 AND COALESCE(jl.is_deleted,0)=0
    GROUP BY je.reference_type ORDER BY 3 DESC
""", (acct_id,))
print("\nGL lines breakdown by je.reference_type (account 15):")
for row in cur.fetchall():
    print(f"  {str(row[0]):<35} count={row[1]:>4} net={row[2]:>15,.2f}")

# SBTs with ref_type='voucher' — check if their JE is posted
cur.execute("""
    SELECT sbt.id, sbt.ref_id, sbt.invoice_id, sbt.direction, sbt.amount_cash,
           je.id as je_id, je.is_posted
    FROM safe_box_transaction sbt
    LEFT JOIN voucher v ON v.id = sbt.ref_id
    LEFT JOIN journal_entry je ON je.reference_type='voucher' AND je.reference_id=v.id
    WHERE sbt.safe_box_id=1 AND sbt.ref_type='voucher'
    ORDER BY sbt.id
""")
rows = cur.fetchall()
unposted = [r for r in rows if r[6] != 1]
print(f"\nSBTs with ref_type='voucher' (SB1): total={len(rows)}, unposted_JE={len(unposted)}")
total_unposted_amount = sum((r[4] if r[3]=='in' else -r[4]) for r in unposted)
print(f"  Total unposted voucher JE SBT net: {total_unposted_amount:,.2f}")
for r in unposted[:10]:
    print(f"  SBT#{r[0]} ref_id={r[1]} inv={r[2]} dir={r[3]} amt={r[4]:,.2f} je_id={r[5]} posted={r[6]}")

con.close()
