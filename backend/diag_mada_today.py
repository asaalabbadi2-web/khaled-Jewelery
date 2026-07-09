"""
diag_mada_today.py
==================
تشخيص مدفوعات مدى اليوم: هل وصلت التسوية أم لا؟

تشغيل:
    docker exec yasargold-backend python backend/diag_mada_today.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from app import app
from models import db
from sqlalchemy import text
from datetime import date

with app.app_context():
    today = str(date.today())
    print(f"=== تشخيص مدى — {today} ===\n")

    # ── 1) IPs مدى اليوم ─────────────────────────────────────────────────────
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
             WHERE sl.invoice_payment_id = ip.id)  AS sl_count,
            (SELECT COALESCE(SUM(sl.amount_settled),0) FROM settlement_line sl
             JOIN voucher v ON v.id = sl.voucher_id
             WHERE sl.invoice_payment_id = ip.id
               AND v.status = 'approved')            AS sl_total
        FROM invoice_payment ip
        JOIN payment_method  pm ON pm.id  = ip.payment_method_id
        WHERE pm.default_safe_box_id = 32
          AND ip.created_at::date = :today
        ORDER BY ip.created_at ASC
    """), {'today': today}).fetchall()

    pending = [r for r in ips if r[11] == 0]
    settled = [r for r in ips if r[11] > 0]

    print(f"IPs مدى اليوم: {len(ips)} إجمالي  |  ✅ مُسوَّى: {len(settled)}  |  ⚠️  pending: {len(pending)}\n")

    if ips:
        pm = ips[0]
        print(f"إعدادات وسيلة الدفع (PM#{pm[4]} — {pm[5]}):")
        print(f"  settlement_days         = {pm[6]}")
        print(f"  commission_timing       = {pm[7]}")
        print(f"  auto_settlement_enabled = {pm[8]}")
        print(f"  settlement_schedule_type= {pm[9]}")
        print(f"  deposit_delay_days      = {pm[10]}")
        print()

    print(f"{'IP':>6}  {'created_at':>19}  {'amount':>8}  {'sl_total':>8}  حالة")
    print("─" * 65)
    for r in ips:
        flag = "✅ مُسوَّى" if r[11] > 0 else "⚠️  pending"
        print(f"  #{r[0]:<5} {str(r[1])[:19]}  {float(r[2]):>8.0f}  {float(r[13]):>8.0f}  {flag}")

    # ── 2) آخر سند تسوية مدى ─────────────────────────────────────────────────
    print(f"\n── آخر 5 سندات تسوية مدى ──")
    vouchers = db.session.execute(text("""
        SELECT DISTINCT
            v.voucher_number,
            v.date::text,
            v.amount_cash,
            v.status,
            COALESCE(SUM(sl.amount_settled), 0) sl_total,
            COUNT(sl.id) sl_count
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

    # ── 3) خلاصة المشكلة ─────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    if pending:
        total_pending = sum(float(r[2]) for r in pending)
        print(f"⚠️  {len(pending)} IP بقيمة {total_pending:,.0f} SAR لم تُسوَّ بعد")
        first = pending[0]
        if not first[8]:
            print(f"   السبب المحتمل: auto_settlement_enabled = False")
        if first[6] == 0:
            print(f"   settlement_days = 0 → التسوية يجب أن تكون فورية")
        else:
            print(f"   settlement_days = {first[6]} → التسوية مجدولة بعد {first[6]} يوم")
    else:
        print("✅ كل IPs مدى اليوم مُسوَّاة")
