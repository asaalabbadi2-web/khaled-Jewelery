"""
diag_safebox_gap.py
====================
يفكّك فجوة SafeBox لكل safe_box ولكل voucher:

  SBT net balance  (IN - OUT)
  ─ SL-based pending
  ═ gap

لكل AV voucher يصنّف الفجوة:
  • legacy_gap         → مرشح لـ HistoricalClearingAdjustment
  • transfer_voucher   → SBT transfer طبيعي بدون SL (صحيح)
  • fully_covered      → SBT = SL، لا فجوة
"""

import sys
sys.path.insert(0, "backend")
from app import app
from models import db, SafeBox, SafeBoxTransaction, InvoicePayment, PaymentMethod, \
    SettlementLine, Voucher
from sqlalchemy import func, case, text

# وسائل الدفع المعروفة (خارج النطاق: tabby, tamara)
OFF_LIMITS_PM_NAMES = {'tabby', 'tamara'}

with app.app_context():
    print("=== تفكيك فجوة SafeBox ===\n")

    safe_boxes = SafeBox.query.order_by(SafeBox.id).all()

    total_gap = 0.0

    for sb in safe_boxes:

        # ── SBT net ──────────────────────────────────────────────────────
        sbt_net = db.session.query(
            func.coalesce(
                func.sum(
                    case(
                        (SafeBoxTransaction.direction == 'in',  SafeBoxTransaction.amount_cash),
                        else_=-SafeBoxTransaction.amount_cash
                    )
                ), 0.0
            )
        ).filter(SafeBoxTransaction.safe_box_id == sb.id).scalar()
        sbt_net = round(float(sbt_net), 2)

        # ── SL-based pending ──────────────────────────────────────────────
        all_ip_ids = [r[0] for r in
            db.session.query(InvoicePayment.id)
            .join(PaymentMethod)
            .filter(PaymentMethod.default_safe_box_id == sb.id).all()]

        if all_ip_ids:
            sl_rows = (db.session.query(
                SettlementLine.invoice_payment_id,
                func.coalesce(func.sum(SettlementLine.amount_settled), 0.0))
                .join(Voucher, Voucher.id == SettlementLine.voucher_id)
                .filter(
                    SettlementLine.invoice_payment_id.in_(all_ip_ids),
                    Voucher.status == 'approved')
                .group_by(SettlementLine.invoice_payment_id).all())
            sl_settled = {r[0]: float(r[1]) for r in sl_rows}
            ip_amounts = {r[0]: float(r[1]) for r in
                db.session.query(InvoicePayment.id, InvoicePayment.amount)
                .filter(InvoicePayment.id.in_(all_ip_ids)).all()}
            sl_pending = round(sum(
                max(0.0, ip_amounts[i] - sl_settled.get(i, 0.0))
                for i in all_ip_ids), 2)
        else:
            sl_pending = 0.0

        gap = round(sbt_net - sl_pending, 2)
        if abs(gap) < 0.01:
            continue

        total_gap += gap

        # اسم PM لهذه الخزينة
        pm = PaymentMethod.query.filter_by(default_safe_box_id=sb.id).first()
        pm_name = pm.name if pm else '—'
        off_limits = pm_name.lower() in OFF_LIMITS_PM_NAMES

        flag = ' ⛔ خارج النطاق' if off_limits else ''
        print(f"SafeBox #{sb.id} — {sb.name or pm_name}{flag}")
        print(f"  SBT net       = {sbt_net:>12,.2f} SAR")
        print(f"  SL pending    = {sl_pending:>12,.2f} SAR")
        print(f"  gap           = {gap:>12,.2f} SAR")

        if off_limits:
            print()
            continue

        # ── تفكيك الفجوة بالـ vouchers ───────────────────────────────────
        voucher_rows = db.session.execute(text("""
            SELECT
                v.id,
                v.voucher_number,
                v.reference_type,
                v.date::text,
                COALESCE(SUM(CASE WHEN sbt.direction='out' THEN sbt.amount_cash ELSE 0 END), 0) AS sbt_out,
                COALESCE(SUM(CASE WHEN sbt.direction='in'  THEN sbt.amount_cash ELSE 0 END), 0) AS sbt_in,
                COALESCE((
                    SELECT SUM(sl.amount_settled)
                    FROM settlement_line sl
                    WHERE sl.voucher_id = v.id
                ), 0) AS sl_total
            FROM voucher v
            JOIN safe_box_transaction sbt ON sbt.ref_id = v.id
                AND sbt.ref_type IN ('voucher','voucher_reversal')
                AND sbt.safe_box_id = :sb_id
            WHERE v.status = 'approved'
            GROUP BY v.id, v.voucher_number, v.reference_type, v.date
            HAVING ABS(
                COALESCE(SUM(CASE WHEN sbt.direction='out' THEN sbt.amount_cash ELSE 0 END), 0)
                - COALESCE(SUM(CASE WHEN sbt.direction='in' THEN sbt.amount_cash ELSE 0 END), 0)
                - COALESCE((
                    SELECT SUM(sl.amount_settled)
                    FROM settlement_line sl WHERE sl.voucher_id = v.id
                ), 0)
            ) > 0.01
            ORDER BY v.date, v.id
        """), {'sb_id': sb.id}).fetchall()

        if voucher_rows:
            print(f"\n  {'voucher':<20} {'ref_type':<25} {'sbt_out':>9} {'sbt_in':>9} "
                  f"{'sl':>9} {'gap':>9}  تصنيف")
            print(f"  {'─'*90}")
            for r in voucher_rows:
                v_id, v_num, ref_type, v_date, sbt_out, sbt_in, sl_total = r
                v_gap = round(float(sbt_out) - float(sbt_in) - float(sl_total), 2)
                if abs(v_gap) < 0.01:
                    continue

                is_transfer = (ref_type in ('safe_box_transfer', 'transfer') or
                               float(sl_total) == 0 and float(sbt_in) > 0)
                if is_transfer:
                    category = 'transfer_voucher ✅'
                elif float(sl_total) == 0:
                    category = 'legacy_gap ⚠️'
                else:
                    category = 'partial_gap ⚠️'

                print(f"  {str(v_num):<20} {str(ref_type):<25} "
                      f"{float(sbt_out):>9,.0f} {float(sbt_in):>9,.0f} "
                      f"{float(sl_total):>9,.0f} {v_gap:>9,.0f}  {category}")
        else:
            print(f"  (لا يوجد voucher بفجوة — الفارق من مصدر آخر)")

        print()

    print(f"{'═'*60}")
    print(f"إجمالي فجوة كل الخزائن = {total_gap:>12,.2f} SAR")
