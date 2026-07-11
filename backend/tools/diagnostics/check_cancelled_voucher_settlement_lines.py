"""
check_cancelled_voucher_settlement_lines.py
=============================================
قراءة فقط. يفحص فرضية جديدة حول AV-2026-00133: هل السندات الملغاة
AV-130/131/132 (id=1646/1647/1648) لا تزال SettlementLine الخاصة بها تُحسَب
ضمن "ما تمت تسويته سابقاً" لنفس الدفعات، رغم إلغائها — وهل هذا ما تسبّب في
أن AV-133 خصّص لتلك الدفعات أقل من حقها الحقيقي؟

كما يحسب حجم هذه الظاهرة على مستوى النظام كاملاً: كم سطر SettlementLine
مرتبط بسند ملغى/مرفوض، وما إجمالي قيمتها.

لا يُعدّل أي بيانات.

تشغيل:
    docker cp backend/check_cancelled_voucher_settlement_lines.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/check_cancelled_voucher_settlement_lines.py
"""

import os
import sys
import json
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, SettlementLine, Voucher, InvoicePayment

TARGET_VOUCHER_IDS = (1646, 1647, 1648, 1649)  # AV-130, AV-131, AV-132, AV-133


def run():
    with app.app_context():
        print("=" * 70)
        print("SettlementLine breakdown لكل سند من 1646..1649")
        print("=" * 70)
        for vid in TARGET_VOUCHER_IDS:
            v = Voucher.query.get(vid)
            if not v:
                print(f"voucher {vid} not found")
                continue
            sl_rows = SettlementLine.query.filter_by(voucher_id=vid).all()
            print(f"\n{v.voucher_number} (id={vid}) | status={v.status} | amount_cash={v.amount_cash:.2f} "
                  f"| cancelled_at={v.cancelled_at} | cancellation_reason={v.cancellation_reason}")
            for sl in sl_rows:
                ip = InvoicePayment.query.get(sl.invoice_payment_id)
                print(f"    SettlementLine#{sl.id} -> IP {sl.invoice_payment_id} "
                      f"(amount={ip.amount if ip else '?'}) | amount_settled={sl.amount_settled:.2f} "
                      f"| created_at={sl.created_at}")

        print()
        print("=" * 70)
        print("حجم الظاهرة على مستوى النظام: SettlementLine مرتبطة بسند ملغى/مرفوض")
        print("=" * 70)
        bad_rows = (
            db.session.query(SettlementLine, Voucher)
            .join(Voucher, Voucher.id == SettlementLine.voucher_id)
            .filter(Voucher.status.in_(('cancelled', 'rejected')))
            .all()
        )
        print(f"عدد سطور SettlementLine المرتبطة بسند ملغى/مرفوض: {len(bad_rows)}")
        total = 0.0
        affected_ips = set()
        details = []
        for sl, v in bad_rows:
            total += sl.amount_settled
            affected_ips.add(sl.invoice_payment_id)
            details.append({
                'settlement_line_id': sl.id,
                'voucher_id': v.id,
                'voucher_number': v.voucher_number,
                'voucher_status': v.status,
                'invoice_payment_id': sl.invoice_payment_id,
                'amount_settled': sl.amount_settled,
            })
            print(f"  SettlementLine#{sl.id} | voucher {v.voucher_number} (status={v.status}) "
                  f"| IP {sl.invoice_payment_id} | amount_settled={sl.amount_settled:.2f}")
        print(f"\nإجمالي القيمة: {total:.2f} | عدد الدفعات المتأثرة: {len(affected_ips)}")

        report = {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'target_vouchers_breakdown_in_console_output': True,
            'cancelled_or_rejected_settlement_lines': details,
            'total_amount': round(total, 2),
            'affected_invoice_payment_count': len(affected_ips),
        }
        reports_dir = os.path.join(os.path.dirname(__file__), 'reports')
        os.makedirs(reports_dir, exist_ok=True)
        path = os.path.join(
            reports_dir,
            f"check_cancelled_voucher_settlement_lines_{datetime.now().strftime('%Y%m%dT%H%M%SZ')}.json",
        )
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        print(f"\nتم كتابة التقرير: {path}")
        print("(قراءة فقط بالكامل)")


if __name__ == '__main__':
    run()
