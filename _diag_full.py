"""
Comprehensive diagnostic: Compare per-invoice SBT vs invoice-JE safe_box debits.
Run this on the PRODUCTION DB to understand the -66K mismatch.
"""
import sqlite3, os

db_path = '/Users/salehalabbadi/yasargold/backend/app.db'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Get safe_box accounts
cur.execute("SELECT id, name, account_id FROM safe_box WHERE account_id IS NOT NULL")
safes = {r['account_id']: {'sb_id': r['id'], 'name': r['name']} for r in cur.fetchall()}
print(f"Safe box accounts: {safes}")

if not safes:
    print("No safe boxes with accounts found!")
    exit()

sb_account_ids = list(safes.keys())

# 1. ALL JE lines on safe_box accounts, grouped by reference_type
print("\n=== GL lines on safe_box accounts by reference_type ===")
cur.execute("""
    SELECT COALESCE(je.reference_type,'NULL') as rt,
           COUNT(*) as cnt,
           ROUND(SUM(COALESCE(jl.cash_debit,0)),2) as tot_debit,
           ROUND(SUM(COALESCE(jl.cash_credit,0)),2) as tot_credit,
           ROUND(SUM(COALESCE(jl.cash_debit,0) - COALESCE(jl.cash_credit,0)),2) as net
    FROM journal_entry_line jl
    JOIN journal_entry je ON je.id = jl.journal_entry_id
    WHERE jl.account_id IN ({})
      AND COALESCE(jl.is_deleted,0)=0
      AND COALESCE(je.is_deleted,0)=0
      AND COALESCE(je.is_draft,0)=0
      AND COALESCE(je.is_posted,1)=1
    GROUP BY je.reference_type
    ORDER BY net DESC
""".format(','.join('?' * len(sb_account_ids))), sb_account_ids)
for r in cur.fetchall():
    print(f"  {r['rt']:20s}: cnt={r['cnt']:4d}, debit={r['tot_debit']:>12.2f}, credit={r['tot_credit']:>12.2f}, net={r['net']:>12.2f}")

# 2. SBT by ref_type
print("\n=== SBT by ref_type ===")
cur.execute("""
    SELECT COALESCE(ref_type,'NULL') as rt,
           COUNT(*) as cnt,
           ROUND(SUM(CASE WHEN direction='in' THEN COALESCE(amount_cash,0) ELSE 0 END),2) as total_in,
           ROUND(SUM(CASE WHEN direction='out' THEN COALESCE(amount_cash,0) ELSE 0 END),2) as total_out,
           ROUND(SUM(CASE WHEN direction='in' THEN COALESCE(amount_cash,0) ELSE -COALESCE(amount_cash,0) END),2) as net
    FROM safe_box_transaction
    GROUP BY ref_type
    ORDER BY net DESC
""")
for r in cur.fetchall():
    print(f"  {r['rt']:24s}: cnt={r['cnt']:4d}, in={r['total_in']:>12.2f}, out={r['total_out']:>12.2f}, net={r['net']:>12.2f}")

# 3. Per-invoice: compare voucher SBT vs voucher GL on safe_box account
print("\n=== Per-voucher: SBT vs Voucher-JE GL on safe_box accounts ===")
cur.execute("""
    WITH voucher_sbt AS (
        SELECT ref_id as voucher_id,
               ROUND(SUM(CASE WHEN direction='in' THEN COALESCE(amount_cash,0) ELSE -COALESCE(amount_cash,0) END),2) as sbt_net
        FROM safe_box_transaction
        WHERE ref_type IN ('voucher','invoice_payment')
        GROUP BY ref_id
    ),
    voucher_gl AS (
        SELECT je.reference_id as voucher_id,
               ROUND(SUM(COALESCE(jl.cash_debit,0) - COALESCE(jl.cash_credit,0)),2) as gl_net
        FROM journal_entry_line jl
        JOIN journal_entry je ON je.id = jl.journal_entry_id
        WHERE je.reference_type = 'voucher'
          AND jl.account_id IN ({accts})
          AND COALESCE(jl.is_deleted,0)=0
          AND COALESCE(je.is_deleted,0)=0
        GROUP BY je.reference_id
    )
    SELECT COALESCE(s.voucher_id, g.voucher_id) as vid,
           COALESCE(s.sbt_net, 0) as sbt,
           COALESCE(g.gl_net, 0) as gl,
           ROUND(COALESCE(s.sbt_net, 0) - COALESCE(g.gl_net, 0), 2) as diff
    FROM voucher_sbt s
    FULL OUTER JOIN voucher_gl g ON s.voucher_id = g.voucher_id
    WHERE ABS(COALESCE(s.sbt_net, 0) - COALESCE(g.gl_net, 0)) > 0.01
    ORDER BY ABS(COALESCE(s.sbt_net, 0) - COALESCE(g.gl_net, 0)) DESC
    LIMIT 20
""".format(accts=','.join('?' * len(sb_account_ids))), sb_account_ids)
rows = cur.fetchall()
if rows:
    for r in rows:
        print(f"  voucher_id={r['vid']}: SBT={r['sbt']}, GL={r['gl']}, diff={r['diff']}")
else:
    print("  All voucher SBT/GL pairs match! (or no data)")

# 4. Invoice-JE lines hitting safe_box accounts (the ones causing potential mismatch)
print("\n=== Invoice JE lines on safe_box accounts ===")
cur.execute("""
    SELECT je.reference_id as invoice_id, je.is_posted,
           jl.account_id,
           ROUND(jl.cash_debit,2) as debit, ROUND(jl.cash_credit,2) as credit,
           ROUND(COALESCE(jl.cash_debit,0) - COALESCE(jl.cash_credit,0),2) as net
    FROM journal_entry_line jl
    JOIN journal_entry je ON je.id = jl.journal_entry_id
    WHERE je.reference_type = 'invoice'
      AND jl.account_id IN ({})
      AND COALESCE(jl.is_deleted,0)=0
      AND COALESCE(je.is_deleted,0)=0
    ORDER BY je.reference_id
    LIMIT 20
""".format(','.join('?' * len(sb_account_ids))), sb_account_ids)
rows = cur.fetchall()
total_inv_net = 0
for r in rows:
    print(f"  invoice={r['invoice_id']}, posted={r['is_posted']}, acct={r['account_id']}, debit={r['debit']}, credit={r['credit']}, net={r['net']}")
    total_inv_net += r['net']
print(f"  TOTAL invoice JE net on safe_box accounts (shown): {round(total_inv_net, 2)}")

# 5. For each invoice that hits safe_box in its JE, check if there's also a voucher for it
print("\n=== Invoice JE-on-safe_box: does a voucher SBT exist for same invoice? ===")
cur.execute("""
    SELECT je.reference_id as invoice_id,
           ROUND(SUM(COALESCE(jl.cash_debit,0) - COALESCE(jl.cash_credit,0)),2) as inv_je_net,
           (SELECT ROUND(SUM(CASE WHEN sbt.direction='in' THEN COALESCE(sbt.amount_cash,0) 
                                  ELSE -COALESCE(sbt.amount_cash,0) END),2)
            FROM safe_box_transaction sbt WHERE sbt.invoice_id = je.reference_id) as sbt_for_invoice,
           (SELECT COUNT(*) FROM voucher v WHERE v.reference_type='invoice' AND v.reference_id=je.reference_id) as voucher_count
    FROM journal_entry_line jl
    JOIN journal_entry je ON je.id = jl.journal_entry_id
    WHERE je.reference_type = 'invoice'
      AND jl.account_id IN ({})
      AND COALESCE(jl.is_deleted,0)=0
      AND COALESCE(je.is_deleted,0)=0
      AND COALESCE(je.is_posted,1)=1
    GROUP BY je.reference_id
    ORDER BY ABS(ROUND(SUM(COALESCE(jl.cash_debit,0) - COALESCE(jl.cash_credit,0)),2) - 
             COALESCE((SELECT ROUND(SUM(CASE WHEN sbt.direction='in' THEN COALESCE(sbt.amount_cash,0) 
                                            ELSE -COALESCE(sbt.amount_cash,0) END),2)
                       FROM safe_box_transaction sbt WHERE sbt.invoice_id = je.reference_id), 0)) DESC
    LIMIT 20
""".format(','.join('?' * len(sb_account_ids))), sb_account_ids)
rows = cur.fetchall()
for r in rows:
    diff = round((r['sbt_for_invoice'] or 0) - (r['inv_je_net'] or 0), 2)
    print(f"  invoice={r['invoice_id']}: inv_je_net={r['inv_je_net']}, sbt_for_invoice={r['sbt_for_invoice']}, vouchers={r['voucher_count']}, diff={diff}")

conn.close()
