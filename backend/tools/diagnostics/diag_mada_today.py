"""
diag_mada_today.py
==================
تشخيص مدفوعات مدى آخر يومين: هل وصلت التسوية أم لا؟

تشغيل:
    docker exec yasargold-backend python backend/diag_mada_today.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from app import app
from models import db
from sqlalchemy import text
from datetime import date, timedelta

with app.app_context():
    today = date.today()
    since = str(today - timedelta(days=1))
    print(f"=== تشخيص مدى — {today} (آخر يومين من {since}) ===\n")

    # ── 1) IPs مدى آخر يومين ─────────────────────────────────────────────────
    ips = db.session.execute(text("""
        SELECT
            ip.id,
            ip.created_at::text,
            ip.amount,
            ip.net_amount,
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
          AND ip.created_at::date >= :since
        ORDER BY ip.created_at ASC
    """), {'since': since}).fetchall()

    pending = [r for r in ips if r[11] == 0]
    settled = [r for r in ips if r[11] > 0]

    print(f"IPs مدى: {len(ips)} إجمالي  |  مسوى: {len(settled)}  |  pending: {len(pending)}\n")

    if ips:
        pm = ips[0]
        print(f"PM#{pm[4]} — {pm[5]}")
        print(f"  settlement_days          = {pm[6]}")
        print(f"  commission_timing        = {pm[7]}")
        print(f"  auto_settlement_enabled  = {pm[8]}")
        print(f"  settlement_schedule_type = {pm[9]}")
        print(f"  deposit_delay_days       = {pm[10]}")
        print()

    print(f"{'IP':>6}  {'created_at':>19}  {'amount':>8}  {'sl_total':>8}  status")
    print("-" * 65)
    for r in ips:
        flag = "OK" if r[11] > 0 else "PENDING"
        print(f"  #{r[0]:<5} {str(r[1])[:19]}  {float(r[2]):>8.0f}  {float(r[12]):>8.0f}  {flag}")

    # ── 2) آخر 5 سندات تسوية مدى ─────────────────────────────────────────────
    print(f"\n--- اخر 5 سندات تسوية مدى ---")
    vouchers = db.session.execute(text("""
        SELECT
            v.id,
            v.voucher_number,
            v.date::text,
            v.amount_cash,
            v.status,
            COALESCE(SUM(sl.amount_settled), 0) sl_total
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
        print(f"  {r[1]}  {str(r[2])[:10]}  cash={float(r[3]):>8.0f}  sl={float(r[5]):>8.0f}  {r[4]}")

    # ── 3) خلاصة ─────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    if pending:
        total = sum(float(r[2]) for r in pending)
        print(f"PENDING: {len(pending)} IP = {total:,.0f} SAR لم تسوى")
        pm0 = pending[0]
        if not pm0[8]:
            print("  >> auto_settlement_enabled = False  <-- المشكله هنا")
        elif int(pm0[6] or 0) == 0:
            print("  >> settlement_days=0 والتسوية لم تشتغل -- تحقق من الـ scheduler")
        else:
            print(f"  >> settlement_days={pm0[6]} -- التسوية مجدوله")
    else:
        print("OK: كل IPs مسواه")
