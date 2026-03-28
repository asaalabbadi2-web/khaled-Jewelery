import sqlite3, os
db = os.path.expanduser("~/yasargold/app.db")
con = sqlite3.connect(db)
cur = con.cursor()

# SBT #12 – what is it?
cur.execute("SELECT id, safe_box_id, ref_type, ref_id, invoice_id, direction, amount_cash FROM safe_box_transaction WHERE id=12")
print("SBT #12:", cur.fetchone())

# The _append_safe_transactions_for_voucher idempotency guard checks:
#   ref_id == voucher.id AND ref_type IN ('voucher', 'invoice_payment')
# For voucher 9: ref_id=9, ref_type='invoice_payment'
# SBT #12 has ref_id=9, ref_type='invoice_payment' -> idempotency guard FIRES even though
# SBT #12 belongs to a different invoice_payment (id=9), not to voucher 9!

# Let's check: what IS invoice_payment id=9?
try:
    cur.execute("SELECT id, invoice_id, amount, payment_method_id FROM invoice_payment WHERE id=9")
    print("InvoicePayment #9:", cur.fetchone())
except Exception as e:
    print("No invoice_payment table or error:", e)

# What voucher is the voucher that created SBT #12?
# ref_type=invoice_payment, ref_id=9 -> this means "ref_id is invoice_payment.id=9"
# But _append_safe_transactions_for_voucher now uses ref_type='invoice_payment' and ref_id=voucher.id!!!
# Wait -- let's re-check the guard code by looking at what note the voucher for SBT #12 has

# The real voucher for SBT #12 has invoice_id=13, so it's an old voucher
cur.execute("SELECT id, voucher_type, amount_cash, reference_type, reference_id, journal_entry_id, notes FROM voucher WHERE id IN (SELECT ref_id FROM safe_box_transaction WHERE id=12)")
print("Voucher for SBT #12:", cur.fetchone())

# Now: for new voucher 9 (invoice 6), the guard checks ref_id=9 AND ref_type IN ('voucher','invoice_payment')
# SBT 12 has ref_id=9, ref_type='invoice_payment' -> COLLISION!
# The guard incorrectly treats invoice_payment.id=9 as voucher.id=9

print("\nConclusion: idempotency guard in _append_safe_transactions_for_voucher")
print("checks ref_id=voucher.id AND ref_type='invoice_payment'")
print("But SBT was created with ref_id=invoice_payment.id which happened to be 9")
print("This causes false positive idempotency block for voucher 9!")
con.close()
