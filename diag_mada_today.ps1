@'
import sys, os
sys.path.insert(0, "backend")
from app import app
from models import db
from sqlalchemy import text
from datetime import date

with app.app_context():
    today = str(date.today())
    print(f"=== تشخيص مدى === {today}\n")

    ips = db.session.execute(text("""
        SELECT
            ip.id,
            ip.created_at::text,
            ip.amount,
            pm.id            AS pm_id,
            pm.name          AS pm_name,
            pm.settlement_days,
            pm.commission_timing,
            pm.auto_settlement_enabled,
            pm.settlement_schedule_type,
            pm.deposit_delay_days,
            (SELECT COUNT(*) FROM settlement_line sl
             WHERE sl.invoice_payment_id = ip.id)         AS sl_count,
            (SELECT COALESCE(SUM(sl.amount_settled),0)
             FROM settlement_line sl
             JOIN voucher v ON v.id = sl.voucher_id
             WHERE sl.invoice_payment_id = ip.id
               AND v.status = 'approved')                  AS sl_total
        FROM invoice_payment ip
        JOIN payment_method  pm ON pm.id = ip.payment_method_id
        WHERE pm.default_safe_box_id = 32
          AND ip.created_at::date = :today
        ORDER BY ip.created_at ASC
    """), {"today": today}).fetchall()

    pending = [r for r in ips if r[10] == 0]
    settled = [r for r in ips if r[10] > 0]
    print(f"IPs اليوم: {len(ips)}  |  مسوى: {len(settled)}  |  pending: {len(pending)}\n")

    if ips:
        pm = ips[0]
        print(f"PM#{pm[3]} — {pm[4]}")
        print(f"  settlement_days          = {pm[5]}")
        print(f"  commission_timing        = {pm[6]}")
        print(f"  auto_settlement_enabled  = {pm[7]}")
        print(f"  settlement_schedule_type = {pm[8]}")
        print(f"  deposit_delay_days       = {pm[9]}")
        print()

    print(f"{'IP':>6}  {'created_at':>19}  {'amount':>8}  {'sl_total':>8}  status")
    print("-" * 65)
    for r in ips:
        flag = "OK" if r[10] > 0 else "PENDING"
        print(f"  #{r[0]:<5} {str(r[1])[:19]}  {float(r[2]):>8.0f}  {float(r[11]):>8.0f}  {flag}")

    print()
    print("--- اخر 5 سندات تسوية مدى ---")
    vouchers = db.session.execute(text("""
        SELECT DISTINCT
            v.voucher_number,
            v.date::text,
            v.amount_cash,
            v.status,
            COALESCE(SUM(sl.amount_settled),0) sl_total
        FROM voucher v
        JOIN settlement_line sl ON sl.voucher_id = v.id
        JOIN invoice_payment ip ON ip.id = sl.invoice_payment_id
        JOIN payment_method  pm ON pm.id = ip.payment_method_id
        WHERE pm.default_safe_box_id = 32
        GROUP BY v.id, v.voucher_number, v.date, v.amount_cash, v.status
        ORDER BY v.id DESC
        LIMIT 5
    """)).fetchall()
    for r in vouchers:
        print(f"  {r[0]}  {str(r[1])[:10]}  cash={float(r[2]):>8.0f}  sl={float(r[4]):>8.0f}  {r[3]}")

    print()
    print("=" * 60)
    if pending:
        total = sum(float(r[2]) for r in pending)
        print(f"PENDING: {len(pending)} IP = {total:,.0f} SAR لم تسوى")
        pm0 = pending[0]
        if not pm0[7]:
            print("  >> auto_settlement_enabled = False  <-- المشكله هنا")
        elif pm0[5] == 0:
            print("  >> settlement_days=0 والتسوية لم تشتغل -- تحقق من الـ scheduler")
        else:
            print(f"  >> settlement_days={pm0[5]} -- التسوية مجدوله")
    else:
        print("OK: كل IPs مسواه")
'@ | docker exec -i yasargold-backend python 2>&1 | Select-String -NotMatch "schema_guard|Auto-migration|Startup bootstrap|psycopg2|Background on this error|FullyQualified"
