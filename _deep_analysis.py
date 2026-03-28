"""Deep analysis of SafeBox GL reconciliation mismatch."""
import sqlite3, os

# Try production DB path first, fall back to local
db_candidates = [
    '/Users/salehalabbadi/yasargold/backend/app.db',
]
db_path = None
for p in db_candidates:
    if os.path.exists(p):
        db_path = p
        break

if not db_path:
    print("ERROR: No database found!")
    exit(1)

print(f"Database: {db_path}")
print(f"Size: {os.path.getsize(db_path) / 1024 / 1024:.1f} MB")

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 1. Safe boxes and their linked accounts
print("\n=== Safe Boxes ===")
cur.execute("SELECT id, name, safe_type, account_id FROM safe_box ORDER BY id")
safes = cur.fetchall()
for sb in safes:
    print(f"  id={sb['id']}, name={sb['name']}, type={sb['safe_type']}, account_id={sb['account_id']}")

# 2. For each safe box, compute SBT total and GL total (all JE types breakdown)
for sb in safes:
    sb_id = sb['id']
    acct_id = sb['account_id']
    if not acct_id:
        continue
    
    print(f"\n=== Safe Box {sb_id}: {sb['name']} (account_id={acct_id}) ===")
    
    # SBT total
    cur.execute("""
        SELECT COUNT(*) as cnt,
               ROUND(SUM(CASE WHEN direction='in' THEN COALESCE(amount_cash,0) ELSE -COALESCE(amount_cash,0) END),2) as net
        FROM safe_box_transaction
        WHERE safe_box_id = ?
    """, (sb_id,))
    sbt = cur.fetchone()
    print(f"  SBT: rows={sbt['cnt']}, net={sbt['net']}")
    
    # SBT by ref_type
    cur.execute("""
        SELECT COALESCE(ref_type,'NULL') as rt, direction, COUNT(*) as cnt,
               ROUND(SUM(COALESCE(amount_cash,0)),2) as total
        FROM safe_box_transaction
        WHERE safe_box_id = ?
        GROUP BY ref_type, direction
        ORDER BY ref_type, direction
    """, (sb_id,))
    print("  SBT breakdown:")
    for r in cur.fetchall():
        print(f"    ref_type={r['rt']}, dir={r['direction']}: cnt={r['cnt']}, total={r['total']}")
    
    # GL total (all)
    cur.execute("""
        SELECT COUNT(*) as cnt,
               ROUND(SUM(COALESCE(jl.cash_debit,0) - COALESCE(jl.cash_credit,0)),2) as net
        FROM journal_entry_line jl
        JOIN journal_entry je ON je.id = jl.journal_entry_id
        WHERE jl.account_id = ?
          AND COALESCE(jl.is_deleted,0)=0
          AND COALESCE(je.is_deleted,0)=0
          AND COALESCE(je.is_draft,0)=0
          AND COALESCE(je.is_posted,1)=1
    """, (acct_id,))
    gl = cur.fetchone()
    print(f"  GL (all posted): rows={gl['cnt']}, net={gl['net']}")
    
    # GL by reference_type
    cur.execute("""
        SELECT COALESCE(je.reference_type,'NULL') as rt, 
               je.is_posted,
               COUNT(*) as cnt,
               ROUND(SUM(COALESCE(jl.cash_debit,0)),2) as tot_debit,
               ROUND(SUM(COALESCE(jl.cash_credit,0)),2) as tot_credit,
               ROUND(SUM(COALESCE(jl.cash_debit,0) - COALESCE(jl.cash_credit,0)),2) as net
        FROM journal_entry_line jl
        JOIN journal_entry je ON je.id = jl.journal_entry_id
        WHERE jl.account_id = ?
          AND COALESCE(jl.is_deleted,0)=0
          AND COALESCE(je.is_deleted,0)=0
          AND COALESCE(je.is_draft,0)=0
        GROUP BY je.reference_type, je.is_posted
        ORDER BY je.reference_type, je.is_posted
    """, (acct_id,))
    print("  GL breakdown by reference_type & is_posted:")
    for r in cur.fetchall():
        print(f"    ref_type={r['rt']}, posted={r['is_posted']}: cnt={r['cnt']}, debit={r['tot_debit']}, credit={r['tot_credit']}, net={r['net']}")
    
    # GL excluding invoice
    cur.execute("""
        SELECT COUNT(*) as cnt,
               ROUND(SUM(COALESCE(jl.cash_debit,0) - COALESCE(jl.cash_credit,0)),2) as net
        FROM journal_entry_line jl
        JOIN journal_entry je ON je.id = jl.journal_entry_id
        WHERE jl.account_id = ?
          AND COALESCE(jl.is_deleted,0)=0
          AND COALESCE(je.is_deleted,0)=0
          AND COALESCE(je.is_draft,0)=0
          AND COALESCE(je.is_posted,1)=1
          AND COALESCE(je.reference_type,'') != 'invoice'
    """, (acct_id,))
    gl_noinv = cur.fetchone()
    print(f"  GL (no invoice, posted): rows={gl_noinv['cnt']}, net={gl_noinv['net']}")
    
    sbt_net = float(sbt['net'] or 0)
    gl_all_net = float(gl['net'] or 0)
    gl_noinv_net = float(gl_noinv['net'] or 0)
    print(f"\n  Diff (SBT - GL all posted):       {round(sbt_net - gl_all_net, 2)}")
    print(f"  Diff (SBT - GL no-invoice posted): {round(sbt_net - gl_noinv_net, 2)}")

# 3. Check if the reconciliation logic is using the right filter
print("\n=== Reconciliation endpoint logic check ===")
# Check what code is loaded
import importlib.util
routes_path = '/Users/salehalabbadi/yasargold/backend/routes.py'
with open(routes_path) as f:
    content = f.read()
    if "reference_type, '') != 'invoice'" in content:
        print("  ✅ Invoice exclusion filter IS present in routes.py")
    else:
        print("  ❌ Invoice exclusion filter NOT found in routes.py")

conn.close()
