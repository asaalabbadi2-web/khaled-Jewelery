import sqlite3

conn = sqlite3.connect("app.db")
cur = conn.cursor()

# 1. Find all JEs that credit bank 757 with ~59250 (the original payment JE-00138 corrects)
print("=== Bank 757 credited ~59250 (original payment) ===")
cur.execute("""
SELECT je.id, je.entry_number, je.reference_type, je.reference_id, je.description,
       jl.id, jl.account_id, a.account_number, a.name,
       jl.cash_debit, jl.cash_credit
FROM journal_entry je
JOIN journal_entry_line jl ON jl.journal_entry_id = je.id AND jl.is_deleted = 0
JOIN account a ON a.id = jl.account_id
WHERE jl.account_id = 757 AND abs(jl.cash_credit - 59250) < 1
AND je.is_deleted = 0
ORDER BY je.id
""")
for r in cur.fetchall():
    print(r)

# 2. Show ALL lines of JE id=176 (JE-2026-00138)
print("\n=== All lines of JE id=176 (JE-2026-00138) ===")
cur.execute("""
SELECT je.id, je.entry_number, je.reference_type, je.reference_id, je.description,
       jl.id, jl.account_id, a.account_number, a.name,
       jl.cash_debit, jl.cash_credit
FROM journal_entry je
JOIN journal_entry_line jl ON jl.journal_entry_id = je.id
JOIN account a ON a.id = jl.account_id
WHERE je.id = 176
ORDER BY jl.id
""")
for r in cur.fetchall():
    print(r)

# 3. Check if JE id=176 has a sibling/related JE (look for any JE with same description or within ±5 id range)
print("\n=== JEs near id=176 with no reference_type ===")
cur.execute("""
SELECT je.id, je.entry_number, je.reference_type, je.reference_id, je.description
FROM journal_entry je
WHERE je.id BETWEEN 170 AND 185 AND je.is_deleted = 0
ORDER BY je.id
""")
for r in cur.fetchall():
    print(r)

# 4. Look for the JE with reference_type=voucher_payment that originally debited bank 757 for 59250
print("\n=== Payment vouchers with bank 757 + ~59250 ===")
cur.execute("""
SELECT je.id, je.entry_number, je.reference_type, je.reference_id, je.description,
       jl.id, jl.account_id, a.account_number, a.name,
       jl.cash_debit, jl.cash_credit
FROM journal_entry je
JOIN journal_entry_line jl ON jl.journal_entry_id = je.id AND jl.is_deleted = 0
JOIN account a ON a.id = jl.account_id
WHERE je.id IN (
    SELECT DISTINCT journal_entry_id FROM journal_entry_line
    WHERE account_id = 757 AND is_deleted = 0
    AND abs(cash_credit - 59250) < 1
)
AND je.is_deleted = 0
ORDER BY je.id, jl.id
""")
for r in cur.fetchall():
    print(r)

conn.close()
