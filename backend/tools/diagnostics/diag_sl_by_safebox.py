"""
diag_sl_by_safebox.py
=====================
يكشف توزيع SettlementLines بين صناديق الدفع المختلفة.
الهدف: هل الـ 208,969 الزائدة تأتي من صناديق غير مدى (safe_box_id != 32)؟

تشغيل:
    docker exec yasargold-backend python backend/diag_sl_by_safebox.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from app import app
from models import db
from sqlalchemy import text

with app.app_context():

    print("=" * 70)
    print("SLs مقسّمة حسب safe_box_id (عبر InvoicePayment → PaymentMethod)")
    print("=" * 70)

    by_box = db.session.execute(text("""
        SELECT
            pm.default_safe_box_id  AS safe_box_id,
            COUNT(sl.id)            AS sl_count,
            COALESCE(SUM(sl.amount_settled), 0)::numeric(14,2) AS sl_total
        FROM settlement_line sl
        JOIN invoice_payment ip ON ip.id = sl.invoice_payment_id
        JOIN payment_method  pm ON pm.id = ip.payment_method_id
        GROUP BY pm.default_safe_box_id
        ORDER BY sl_total DESC
    """)).fetchall()

    grand = 0.0
    for r in by_box:
        marker = " ← مدى (الهدف)" if r[0] == 32 else ""
        print(f"  safe_box={r[0]}  {r[1]:>4} SLs  {float(r[2]):>12,.0f} SAR{marker}")
        grand += float(r[2])
    print(f"  {'─'*50}")
    print(f"  المجموع الكلي:       {grand:>12,.0f} SAR")

    print()
    print("=" * 70)
    print("مقارنة SL مقابل amount_cash لكل سند approved (AV-2026)")
    print("يظهر فقط السندات التي يختلف فيها SL عن amount_cash بأكثر من 1 ريال")
    print("=" * 70)

    discrepancies = db.session.execute(text("""
        SELECT
            v.voucher_number,
            v.date::text,
            COALESCE(v.amount_cash, 0)::numeric(12,0)          AS cash,
            COALESCE(SUM(sl.amount_settled), 0)::numeric(12,0) AS sl_total,
            (COALESCE(SUM(sl.amount_settled), 0)
             - COALESCE(v.amount_cash, 0))::numeric(12,0)      AS diff
        FROM voucher v
        LEFT JOIN settlement_line sl ON sl.voucher_id = v.id
        WHERE v.status = 'approved'
          AND v.voucher_number LIKE 'AV-2026-%'
        GROUP BY v.id, v.voucher_number, v.date, v.amount_cash
        HAVING ABS(COALESCE(SUM(sl.amount_settled),0) - COALESCE(v.amount_cash,0)) > 1
        ORDER BY ABS(COALESCE(SUM(sl.amount_settled),0) - COALESCE(v.amount_cash,0)) DESC
    """)).fetchall()

    if discrepancies:
        print(f"  {'السند':<25} {'التاريخ':<12} {'amount_cash':>10} {'sl_total':>10} {'فرق':>8}")
        print(f"  {'─'*70}")
        for r in discrepancies:
            flag = " *** زائد" if int(r[4]) > 0 else " *** ناقص"
            print(f"  {r[0]:<25} {str(r[1])[:10]:<12} "
                  f"{int(r[2]):>10,} {int(r[3]):>10,} {int(r[4]):>8,}{flag}")
    else:
        print("  ✅ لا توجد فوارق — كل سند SL == amount_cash")

    print()
    print("=" * 70)
    print("إجماليات كاملة للمقارنة")
    print("=" * 70)

    totals = db.session.execute(text("""
        SELECT
            COUNT(DISTINCT v.id)                                AS vouchers,
            COALESCE(SUM(v.amount_cash), 0)::numeric(14,2)     AS total_cash,
            COALESCE(SUM(sl.amount_settled), 0)::numeric(14,2) AS total_sl,
            COUNT(sl.id)                                        AS sl_rows
        FROM voucher v
        LEFT JOIN settlement_line sl ON sl.voucher_id = v.id
        WHERE v.status = 'approved'
          AND v.voucher_number LIKE 'AV-2026-%'
    """)).fetchone()

    print(f"  سندات approved AV-2026 : {totals[0]}")
    print(f"  مجموع amount_cash      : {float(totals[1]):>12,.0f} SAR")
    print(f"  مجموع SL               : {float(totals[2]):>12,.0f} SAR")
    print(f"  عدد SL rows            : {totals[3]}")
    print(f"  فرق (SL - cash)        : {float(totals[2]) - float(totals[1]):>12,.0f} SAR")
