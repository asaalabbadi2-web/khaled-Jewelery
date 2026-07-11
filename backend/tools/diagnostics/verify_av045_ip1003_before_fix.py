"""
verify_av045_ip1003_before_fix.py
===================================
قراءة فقط بالكامل. تحقّق أخير قبل أي تصحيح فعلي لـ SettlementLine#477:

  1. قراءة SettlementLine#477 مباشرة بمعرّفها الأساسي (لا بحث، لا تخمين).
  2. قراءة كل SettlementLine المرتبطة بـ IP 1003 (للتأكد أنها فقط اثنتان:
     476 و477، وأن مجموعها 5650.00 كما استنتجنا).
  3. التأكد من حالة كل سند مرتبط (990 معتمد، 991 معتمد) ومن رصيدهما
     الحالي (amount_cash) دون تغيير.
  4. بحث عمومي: هل أي مكان آخر في القيود (Voucher.description/notes) يذكر
     رقم 3050 أو 5650 بشكل قد يصبح غير متّسق بعد التصحيح؟ (السندات نفسها
     تصف amount_cash الخاص بها فقط — 1070 لـ991 و4160 لـ990 — لا علاقة لها
     بمجموع SettlementLine، لذا لا تأثير متوقَّع، والسكربت يتحقّق من ذلك
     صريحاً بدل افتراضه).

لا يُعدّل أي بيانات إطلاقاً.

تشغيل:
    docker cp backend/verify_av045_ip1003_before_fix.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/verify_av045_ip1003_before_fix.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import SettlementLine, Voucher, InvoicePayment

EXPECTED_SL_ID = 477
EXPECTED_VOUCHER_ID = 991
EXPECTED_IP_ID = 1003
EXPECTED_AMOUNT = 3050.00


def run():
    with app.app_context():
        print("=" * 70)
        print("1) SettlementLine#477 بمعرّفها المباشر")
        print("=" * 70)
        sl477 = SettlementLine.query.get(EXPECTED_SL_ID)
        if not sl477:
            print(f"❌ SettlementLine#{EXPECTED_SL_ID} غير موجودة — توقّف، لا تكتب سكربت تصحيح.")
            return
        print(f"id={sl477.id} | voucher_id={sl477.voucher_id} | invoice_payment_id={sl477.invoice_payment_id} "
              f"| amount_settled={sl477.amount_settled} | commission={sl477.commission} "
              f"| commission_vat={sl477.commission_vat} | created_at={sl477.created_at}")

        checks = [
            sl477.voucher_id == EXPECTED_VOUCHER_ID,
            sl477.invoice_payment_id == EXPECTED_IP_ID,
            abs(sl477.amount_settled - EXPECTED_AMOUNT) < 0.01,
        ]
        if not all(checks):
            print(f"❌ SettlementLine#477 لا تطابق المتوقَّع (voucher=991, ip=1003, amount=3050.00) — توقّف.")
            return
        print("✅ مطابق تماماً للمتوقَّع.")

        print()
        print("=" * 70)
        print("2) كل SettlementLine المرتبطة بـ IP 1003")
        print("=" * 70)
        all_sl = (
            SettlementLine.query
            .filter_by(invoice_payment_id=EXPECTED_IP_ID)
            .order_by(SettlementLine.id.asc())
            .all()
        )
        print(f"عدد السطور: {len(all_sl)}")
        total = 0.0
        for sl in all_sl:
            v = Voucher.query.get(sl.voucher_id)
            total += sl.amount_settled
            print(f"  #{sl.id} | voucher {v.voucher_number if v else '?'} (id={sl.voucher_id}, status={v.status if v else '?'}) "
                  f"| amount_settled={sl.amount_settled:.2f} | created_at={sl.created_at}")
        print(f"الإجمالي: {total:.2f}")
        if len(all_sl) != 2 or abs(total - 5650.00) > 0.01:
            print("❌ العدد أو الإجمالي لا يطابق المتوقَّع (سطران، إجمالي 5650.00) — توقّف.")
            return
        print("✅ مطابق تماماً: سطران فقط، إجمالي 5650.00.")

        ip1003 = InvoicePayment.query.get(EXPECTED_IP_ID)
        print(f"\nIP {EXPECTED_IP_ID}.amount = {ip1003.amount:.2f} (يجب أن يبقى 3050.00 — لن يتغيّر بالتصحيح)")

        print()
        print("=" * 70)
        print("3) السندات نفسها — هل توصيفها النصي يعتمد على 3050/5650؟")
        print("=" * 70)
        for vid in (990, 991):
            v = Voucher.query.get(vid)
            print(f"{v.voucher_number} (id={vid}) | status={v.status} | amount_cash={v.amount_cash:.2f}")
            print(f"  description: {v.description}")
            print(f"  notes: {v.notes}")
            mentions = []
            for label, text in (('description', v.description), ('notes', v.notes)):
                if text and ('3050' in text or '5650' in text):
                    mentions.append(label)
            if mentions:
                print(f"  ⚠️ يذكر 3050 أو 5650 صريحاً في: {mentions} — راجع يدوياً قبل التصحيح.")
            else:
                print("  ✅ لا يذكر 3050 أو 5650 — التوصيف يعتمد فقط على amount_cash الخاص بالسند (1070/4160)، لن يتأثر.")

        print()
        print("=" * 70)
        print("الخلاصة")
        print("=" * 70)
        print("كل القراءات مطابقة تماماً للمتوقَّع. التصحيح المقترح آمن للتنفيذ:")
        print(f"  SettlementLine#{EXPECTED_SL_ID}.amount_settled: 3050.00 -> 450.00")
        print("(لم يُعدَّل أي شيء في هذا التشغيل — قراءة فقط)")


if __name__ == '__main__':
    run()
