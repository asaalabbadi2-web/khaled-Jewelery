"""
diag_recent_settlements.py
===========================
تشخيص سريع: IPs يوليو8-9 وعلاقتها بسندات التسوية.
يكشف إذا كانت IPs حديثة مُسوَّاة بسندات ذات تواريخ أقدم (علامة خطر).

تشغيل:
    docker exec yasargold-backend python backend/diag_recent_settlements.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from app import app
from models import db, SettlementLine, InvoicePayment, Voucher, PaymentMethod
from datetime import datetime, timezone

SAFE_BOX_ID = 32

with app.app_context():
    run_dt = datetime.now(timezone.utc)
    print(f"=== تشخيص التسويات الأخيرة | {run_dt.strftime('%Y-%m-%d %H:%M')} UTC ===\n")

    # ── 1) كل IPs آخر 5 أيام للصندوق 32 ────────────────────────────────────
    recent_ips = (
        InvoicePayment.query
        .join(PaymentMethod, PaymentMethod.id == InvoicePayment.payment_method_id)
        .filter(
            PaymentMethod.default_safe_box_id == SAFE_BOX_ID,
            InvoicePayment.created_at >= '2026-07-05',
        )
        .order_by(InvoicePayment.created_at.asc())
        .all()
    )
    print(f"IPs للصندوق {SAFE_BOX_ID} منذ يوليو5: {len(recent_ips)}\n")

    # ── 2) لكل IP: أي سند استوعبه؟ ─────────────────────────────────────────
    anomalies = []
    print(f"{'IP':>7} {'created_at':>20} {'amount':>7}  {'السند':>20} {'تاريخ السند':>12} {'فارق الأيام':>12}")
    print("-" * 85)
    for ip in recent_ips:
        sls = SettlementLine.query.filter_by(invoice_payment_id=ip.id).all()
        ip_dt = ip.created_at
        if not sls:
            print(f"  #{ip.id:>5} {str(ip_dt)[:19]:>20} {float(ip.amount):>7.0f}  {'(غير مُسوَّى)':>20}")
            continue
        for sl in sls:
            v = Voucher.query.get(sl.voucher_id)
            if not v:
                continue
            v_dt = v.date if hasattr(v.date, 'date') else v.date
            # حساب الفارق بالأيام بين IP creation وتاريخ السند
            try:
                ip_date = ip_dt.date() if hasattr(ip_dt, 'date') else ip_dt
                v_date  = v_dt.date()  if hasattr(v_dt, 'date')  else v_dt
                delta   = (v_date - ip_date).days
            except Exception:
                delta = None

            flag = ''
            if delta is not None and delta < -1:
                flag = f'  ⚠️  السند أقدم بـ {abs(delta)} يوم!'
                anomalies.append({
                    'ip_id': ip.id,
                    'ip_created': str(ip_dt)[:19],
                    'ip_amount': float(ip.amount),
                    'voucher': v.voucher_number,
                    'voucher_date': str(v_date),
                    'days_diff': delta,
                })
            delta_str = f"{delta:+d}d" if delta is not None else "؟"
            print(f"  #{ip.id:>5} {str(ip_dt)[:19]:>20} {float(ip.amount):>7.0f}  "
                  f"{v.voucher_number:>20} {str(v_date):>12} {delta_str:>12}{flag}")

    # ── 3) ملخص الشذوذات ─────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    if anomalies:
        print(f"⚠️  شذوذات: {len(anomalies)} IP مُسوَّاة بسند أقدم من تاريخ إنشائها")
        for a in anomalies:
            print(f"  IP#{a['ip_id']} ({a['ip_amount']:.0f} ريال، أُنشئ {a['ip_created'][:10]}) "
                  f"→ {a['voucher']} ({a['voucher_date']}) | الفارق: {a['days_diff']}d")
    else:
        print("✅ لا شذوذات — كل IP مُسوَّاة بسند بتاريخ متزامن أو أحدث")

    # ── 4) السندات المنشأة اليوم (يوليو8) ──────────────────────────────────
    print(f"\n── سندات التسوية المنشأة يوليو8 ──")
    vouchers_today = (
        Voucher.query
        .filter(
            Voucher.voucher_number.like('AV-2026-%'),
            Voucher.date >= '2026-07-08',
            Voucher.date <  '2026-07-09',
        )
        .order_by(Voucher.id.asc())
        .all()
    )
    if vouchers_today:
        for v in vouchers_today:
            sl_total = sum(sl.amount_settled for sl in SettlementLine.query.filter_by(voucher_id=v.id).all())
            print(f"  {v.voucher_number} | amount={float(v.amount_cash or 0):.0f} | SL_total={sl_total:.0f} | {v.status}")
    else:
        print("  لا سندات مسجّلة بتاريخ يوليو8")
