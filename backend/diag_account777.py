"""
diag_account777.py
===================
يظهر كل القيود المحاسبية لـ account 777 (مقاصة مدى)
لفهم مصدر رصيد الـ 3,700 في الـ GL.
"""
import sys
sys.path.insert(0, "backend")
from app import app
from models import db, SafeBox, Account
from sqlalchemy import text

SAFE_BOX_ID = 32

with app.app_context():
    sb = SafeBox.query.get(SAFE_BOX_ID)
    acc = Account.query.get(sb.account_id) if sb else None
    print(f"\n=== Safe Box #{SAFE_BOX_ID}: {sb.name if sb else '?'} ===")
    print(f"    account_id = {sb.account_id if sb else '?'}")
    print(f"    account    = {acc.account_number if acc else '?'} — {acc.name if acc else '?'}\n")

    acc_id = sb.account_id if sb else None
    if not acc_id:
        print("لا يوجد account مرتبط")
        sys.exit(1)

    rows = db.session.execute(text("""
        SELECT jel.id,
               je.date,
               je.description,
               je.reference_type,
               je.reference_id,
               jel.cash_debit,
               jel.cash_credit,
               jel.description AS line_desc
        FROM journal_entry_line jel
        JOIN journal_entry je ON je.id = jel.journal_entry_id
        WHERE jel.account_id = :acc_id
        ORDER BY je.date, je.id, jel.id
    """), {'acc_id': acc_id}).fetchall()

    running = 0.0
    print(f"  {'date':<12}  {'ref_type':<30}  {'ref_id':>8}  {'debit':>12}  {'credit':>12}  {'running':>12}  note")
    print(f"  {'─'*110}")
    for r in rows:
        jel_id, date, je_desc, ref_type, ref_id, dr, cr, note = r
        dr, cr = float(dr or 0), float(cr or 0)
        running += dr - cr
        date_str = str(date)[:10] if date else '—'
        desc_short = str(note or je_desc or '')[:40]
        print(f"  {date_str:<12}  {str(ref_type or '—'):<30}  {str(ref_id or ''):>8}  "
              f"{dr:>12,.2f}  {cr:>12,.2f}  {running:>12,.2f}  {desc_short}")

    print(f"\n  رصيد نهائي = {running:>12,.2f}")
