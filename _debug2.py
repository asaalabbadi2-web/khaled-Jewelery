import sqlite3

for db_path in ['/Users/salehalabbadi/yasargold/app.db', '/Users/salehalabbadi/yasargold/backend/app.db']:
    print(f"\n=== {db_path} ===")
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT id, name, safe_type FROM safe_box WHERE safe_type='cash' ORDER BY id")
        rows = c.fetchall()
        print("Cash safe boxes:", rows)
        
        c.execute("""
SELECT je.reference_type, COUNT(DISTINCT je.reference_id), ROUND(SUM(jl.cash_debit-jl.cash_credit),2)
FROM journal_entry je JOIN journal_entry_line jl ON jl.journal_entry_id=je.id
JOIN safe_box sb ON sb.account_id=jl.account_id AND sb.safe_type='cash'
WHERE je.is_posted=1 AND COALESCE(je.is_deleted,0)=0 AND COALESCE(jl.is_deleted,0)=0
GROUP BY je.reference_type
ORDER BY ABS(SUM(jl.cash_debit-jl.cash_credit)) DESC
""")
        print("GL by reference_type:")
        for r in c.fetchall():
            print(" ", r)

        c.execute("""
SELECT sbt.safe_box_id, sb.name, ROUND(SUM(CASE WHEN sbt.direction='in' THEN sbt.amount_cash ELSE -sbt.amount_cash END),2)
FROM safe_box_transaction sbt JOIN safe_box sb ON sb.id=sbt.safe_box_id
WHERE sb.safe_type='cash' AND LOWER(COALESCE(sbt.ref_type,''))!='shift_closing_settlement'
GROUP BY sbt.safe_box_id
""")
        print("SBT by safe_box:")
        for r in c.fetchall():
            print(" ", r)
        conn.close()
    except Exception as e:
        print(f"Error: {e}")
