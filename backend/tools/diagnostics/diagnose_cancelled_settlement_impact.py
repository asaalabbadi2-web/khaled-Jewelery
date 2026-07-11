"""
diagnose_cancelled_settlement_impact.py
==========================================
تشخيص فقط -- لا يكتب أي شيء.

السياق: عند بناء SettlementStateService، وُجد أن موضعاً واحداً فقط من 10
مواضع تجمع SettlementLine.amount_settled (routes.py:31108-31127، عند إنشاء
سند تسوية جديد) يفلتر بشرط Voucher.status == 'approved'. الـ9 الباقية
(دوال الجدولة في clearing_settlement_scheduler.py + التسوية المؤجلة في
routes.py:31631) تجمع كل صفوف SettlementLine بلا أي شرط على حالة السند.

cancel_voucher() (routes.py) يغيّر voucher.status فقط -- لا يحذف أي
SettlementLine مرتبط. إذن: لو أُلغي سند تسوية بعد إنشائه، ستستمر الـ9
مواضع في اعتبار الدفعات المرتبطة "مسوّاة فعلاً" إلى الأبد، رغم أن سند
التسوية الفعلي أُلغي ولم يتحرك المال.

هذا السكريبت يكشف: هل هذا له أثر فعلي على بيانات الإنتاج الحالية، أم
احتمال نظري لم يتحقق بعد؟ يبحث عن أي دفعة (InvoicePayment) لها فرق بين
"إجمالي المسوّى عبر كل السندات" و"إجمالي المسوّى عبر السندات المعتمدة فقط".

تشغيل (قراءة فقط، لا حاجة لـ--apply):
    docker exec yasargold-backend python backend/diagnose_cancelled_settlement_impact.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, SettlementLine, Voucher, InvoicePayment
from sqlalchemy import func


def run():
    with app.app_context():
        rows = (
            db.session.query(
                SettlementLine.invoice_payment_id,
                Voucher.status,
                Voucher.voucher_number,
                SettlementLine.amount_settled,
            )
            .join(Voucher, Voucher.id == SettlementLine.voucher_id)
            .all()
        )

        by_ip_all = {}
        by_ip_approved = {}
        non_approved_lines = []

        for ip_id, status, voucher_number, amount in rows:
            amount = float(amount or 0.0)
            by_ip_all[ip_id] = by_ip_all.get(ip_id, 0.0) + amount
            if status == 'approved':
                by_ip_approved[ip_id] = by_ip_approved.get(ip_id, 0.0) + amount
            else:
                non_approved_lines.append((ip_id, status, voucher_number, amount))

        print(f"إجمالي صفوف SettlementLine المفحوصة: {len(rows)}")
        print(f"صفوف مرتبطة بسند غير معتمد (status != 'approved'): {len(non_approved_lines)}\n")

        if not non_approved_lines:
            print("✅ لا توجد أي صفوف SettlementLine مرتبطة بسند غير معتمد حالياً.")
            print("   الفرق بين المواضع الـ10 نظري فقط على البيانات الحالية -- لا أثر فعلي بعد.")
            return 0

        print("تفاصيل الصفوف المرتبطة بسند غير معتمد:")
        for ip_id, status, voucher_number, amount in non_approved_lines:
            print(f"   IP#{ip_id} | سند {voucher_number} | status={status} | amount_settled={amount:.2f}")

        affected_ips = sorted(set(by_ip_all) - set())
        affected = []
        for ip_id in by_ip_all:
            total_all = round(by_ip_all.get(ip_id, 0.0), 2)
            total_approved = round(by_ip_approved.get(ip_id, 0.0), 2)
            if abs(total_all - total_approved) > 0.005:
                affected.append((ip_id, total_all, total_approved))

        print(f"\n{'='*60}")
        if not affected:
            print("✅ بالرغم من وجود صفوف على سندات غير معتمدة، لا توجد دفعة")
            print("   واحدة فيها فرق فعلي بين الإجمالي الكامل والإجمالي المعتمد فقط")
            print("   (مثلاً: قد يكون لها أيضاً تسوية معتمدة بنفس المبلغ من سند آخر).")
            return 0

        print(f"❌ {len(affected)} دفعة متأثرة فعلياً -- المواضع التي لا تفلتر بـ'approved'")
        print("   تراها 'مسوّاة' بمبلغ أكبر من الصحيح:\n")
        total_phantom = 0.0
        for ip_id, total_all, total_approved in affected:
            ip = InvoicePayment.query.get(ip_id)
            phantom = round(total_all - total_approved, 2)
            total_phantom += phantom
            print(
                f"   IP#{ip_id} (invoice_id={getattr(ip, 'invoice_id', '?')}, "
                f"amount={getattr(ip, 'amount', '?')}) | "
                f"مسوّى (الكل)={total_all:.2f} | مسوّى (معتمد فقط)={total_approved:.2f} | "
                f"فرق وهمي={phantom:.2f}"
            )
        print(f"\nإجمالي المبلغ 'المسوّى وهمياً' عبر كل الدفعات المتأثرة: {round(total_phantom, 2):.2f}")
        return 1


if __name__ == '__main__':
    sys.exit(run())
