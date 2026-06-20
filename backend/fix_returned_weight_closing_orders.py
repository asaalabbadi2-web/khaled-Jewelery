"""
fix_returned_weight_closing_orders.py
=======================================
تصحيح تاريخي لأوامر تسكير الوزن (WeightClosingOrder) المرتبطة بفواتير بيع
أُرجعت بالكامل 100%، ولم يُحدَّث وزنها الإجمالي عند المرتجع بسبب خلل قديم في
معالج "مرتجع بيع" بـ routes.py: كان الكود يُعدّل remaining_weight_main_karat
مباشرة بدل total_weight_main_karat، فلا يدوم التعديل لأن
_auto_consume_weight_closing يعيد حساب remaining دائماً من (total - executed)
عند أي تنفيذ لاحق. تم إصلاح ذلك الخلل في الكود (يمنع تكراره مستقبلاً)، لكن
الإصلاح لا يلمس السجلات القديمة المتأثرة فعلياً - وهذا ما يقوم به هذا السكربت.

الفواتير الأربع المتأثرة في الإنتاج (تم التحقق المباشر من قاعدة بيانات
الإنتاج عبر API بتاريخ التصحيح: كل فاتورة أُرجعت بالكامل 100% بنفس الوزن
تماماً، وكل أمر تسكير له executed_weight_main_karat = 0 أي لم يُسوَّ نقدياً
أبداً - لا حاجة لعكس أي قيد COGS):

  invoice_id  invoice_number    returned_by (مرتجع)   weight (جم)
  1078        SELL-2026-511     1089 (SELL-2026-RET..) 5.6
  998         SELL-2026-494     1035                   18.6
  976         SELL-2026-486     1032                   4.6
  881         SELL-2026-444     946                    4.7

التصحيح: لكل أمر من الأربعة (المُطابَق عبر invoice_id لا عبر order.id):
  total_weight_main_karat     -> 0.0
  executed_weight_main_karat  -> 0.0   (تبقى كما هي، فعلاً 0 مسبقاً)
  remaining_weight_main_karat -> 0.0
  status                      -> 'cancelled'
وتحديث حقول المرآة المقابلة على الفاتورة الأصلية (weight_closing_status/
total/executed/remaining).

ضمان أمان: السكربت يتخطّى (لا يُصحّح) أي أمر من الأربعة لو وجد فعلياً
executed_weight_main_karat != 0 وقت التشغيل (أي تمت تسويته نقدياً منذ
التحقق أعلاه) - تلك الحالة تحتاج مراجعة يدوية لا تصحيحاً آلياً.

قبل أي --apply يُكتب تقرير كامل (JSON في backend/reports/) بالقيم قبل/بعد
لكل أمر، بصرف النظر عن --apply.

تشغيل (على نفس الجهاز/الحاوية التي تشغّل قاعدة بيانات الإنتاج):
    docker cp backend/fix_returned_weight_closing_orders.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/fix_returned_weight_closing_orders.py            # dry run + تقرير
    docker exec yasargold-backend python backend/fix_returned_weight_closing_orders.py --apply     # تطبيق فعلي + تقرير

الوضع الافتراضي: DRY RUN (لا يُحفظ شيء في قاعدة البيانات، لكن التقرير يُكتب دائمًا).
"""

import os
import sys
import json
import argparse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, WeightClosingOrder, Invoice

AFFECTED_INVOICE_IDS = (1078, 998, 976, 881)
EPS = 1e-4


def run(apply: bool):
    with app.app_context():
        run_dt = datetime.now(timezone.utc)
        print(f"\n{'=' * 60}")
        print(f"{'تطبيق فعلي' if apply else 'DRY RUN — لن يُحفظ شيء في قاعدة البيانات'}")
        print(f"تاريخ التنفيذ: {run_dt.isoformat()}")
        print(f"{'=' * 60}\n")

        order_rows = []
        skipped_rows = []

        for inv_id in AFFECTED_INVOICE_IDS:
            order = WeightClosingOrder.query.filter_by(invoice_id=inv_id).first()
            invoice = Invoice.query.get(inv_id)

            if not order or not invoice:
                msg = f"لم يُعثر على أمر تسكير أو فاتورة لـ invoice_id={inv_id}"
                print(f"⚠️  تخطّي - {msg}")
                skipped_rows.append({'invoice_id': inv_id, 'reason': msg})
                continue

            before = {
                'total_weight_main_karat': order.total_weight_main_karat,
                'executed_weight_main_karat': order.executed_weight_main_karat,
                'remaining_weight_main_karat': order.remaining_weight_main_karat,
                'status': order.status,
            }

            if abs(float(order.executed_weight_main_karat or 0.0)) > EPS:
                msg = (
                    f"executed_weight_main_karat != 0 ({order.executed_weight_main_karat}) "
                    f"- تمت تسوية جزء نقدياً، يحتاج مراجعة يدوية لا تصحيحاً آلياً"
                )
                print(f"⚠️  تخطّي أمر invoice_id={inv_id} - {msg}")
                skipped_rows.append({'invoice_id': inv_id, 'reason': msg, 'state': before})
                continue

            order_rows.append({
                'invoice_id': inv_id,
                'invoice_number': invoice.invoice_number,
                'order_id': order.id,
                'order_number': order.order_number,
                'before': before,
            })

            if apply:
                order.total_weight_main_karat = 0.0
                order.executed_weight_main_karat = 0.0
                order.remaining_weight_main_karat = 0.0
                order.status = 'cancelled'

                invoice.weight_closing_status = 'cancelled'
                invoice.weight_closing_total_weight = 0.0
                invoice.weight_closing_executed_weight = 0.0
                invoice.weight_closing_remaining_weight = 0.0

        print(f"\nعدد الأوامر المُصحَّحة: {len(order_rows)}")
        for row in order_rows:
            b = row['before']
            print(
                f"  - فاتورة {row['invoice_number']} (order {row['order_number']}): "
                f"total {b['total_weight_main_karat']} -> 0.0, "
                f"remaining {b['remaining_weight_main_karat']} -> 0.0, "
                f"status '{b['status']}' -> 'cancelled'"
            )
        if skipped_rows:
            print(f"\nعدد الأوامر المُتخطّاة: {len(skipped_rows)}")

        report = {
            'run_at': run_dt.isoformat(),
            'applied': apply,
            'affected_invoice_ids': list(AFFECTED_INVOICE_IDS),
            'orders_corrected': order_rows,
            'orders_skipped': skipped_rows,
        }

        reports_dir = os.path.join(os.path.dirname(__file__), 'reports')
        os.makedirs(reports_dir, exist_ok=True)
        report_path = os.path.join(
            reports_dir,
            f"fix_returned_weight_closing_orders_{run_dt.strftime('%Y%m%dT%H%M%SZ')}"
            f"{'_applied' if apply else '_dryrun'}.json"
        )
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\nتم كتابة التقرير: {report_path}")

        if apply:
            db.session.commit()
            print(f"\n✅ تم الحفظ. عدد الأوامر المُصحَّحة: {len(order_rows)}")
        else:
            db.session.rollback()
            print("\n(DRY RUN) لتطبيق التغييرات فعليًا أضف --apply")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    run(apply=args.apply)
