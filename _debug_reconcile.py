import sqlite3
conn = sqlite3.connect('app.db')
c = conn.cursor()

c.execute("""
SELECT je.reference_type, COUNT(DISTINCT je.reference_id), ROUND(SUM(jl.cash_debit-jl.cash_credit),2)
FROM journal_entry je
JOIN journal_entry_line jl ON jl.journal_entry_id=je.id
JOIN safe_box sb ON sb.account_id=jl.account_id AND sb.id=1
WHERE je.is_posted=1 AND COALESCE(je.is_deleted,0)=0 AND COALESCE(jl.is_deleted,0)=0
GROUP BY je.reference_type
ORDER BY ABS(SUM(jl.cash_debit-jl.cash_credit)) DESC
""")
print('GL breakdown by reference_type (safe_box_id=1):')
for row in c.fetchall():
    print(f'  ref_type={row[0]} | count={row[1]} | signed_total={row[2]}')

c.execute("""
SELECT COUNT(*), ROUND(SUM(CASE WHEN direction='in' THEN amount_cash ELSE -amount_cash END),2)
FROM safe_box_transaction WHERE safe_box_id=1 AND LOWER(COALESCE(ref_type,''))!='shift_closing_settlement'
""")
row = c.fetchone()
print(f'SBT: count={row[0]}, signed_total={row[1]}')

# Check invoices that have BOTH an invoice-JE and a voucher-JE hitting safe_box 1
c.execute("""
SELECT COUNT(*), ROUND(SUM(inv_je + vch_je),2) as double_counted
FROM (
  SELECT je.reference_id as inv_id,
    SUM(jl.cash_debit-jl.cash_credit) as inv_je
  FROM journal_entry je
  JOIN journal_entry_line jl ON jl.journal_entry_id=je.id
  JOIN safe_box sb ON sb.account_id=jl.account_id AND sb.id=1
  WHERE je.reference_type='invoice' AND je.is_posted=1
    AND COALESCE(je.is_deleted,0)=0 AND COALESCE(jl.is_deleted,0)=0
  GROUP BY je.reference_id
) inv_je
JOIN (
  SELECT v.invoice_id as inv_id,
    SUM(jl.cash_debit-jl.cash_credit) as vch_je
  FROM voucher v
  JOIN journal_entry je ON je.reference_type='voucher' AND je.reference_id=v.id
  JOIN journal_entry_line jl ON jl.journal_entry_id=je.id
  JOIN safe_box sb ON sb.account_id=jl.account_id AND sb.id=1
  WHERE je.is_posted=1 AND COALESCE(je.is_deleted,0)=0 AND COALESCE(jl.is_deleted,0)=0
  GROUP BY v.invoice_id
) vch_je USING (inv_id)
WHERE inv_je.inv_je != 0 AND vch_je.vch_je != 0
""")
row = c.fetchone()
print(f'Invoices with BOTH invoice-JE and voucher-JE on safe_box 1: count={row[0]}, double_amount={row[1]}')

conn.close()
