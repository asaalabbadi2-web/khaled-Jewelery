"""
backfill_ledger_balance_adjustments.py
========================================
حل جذري نهائي لفروقات وزن الذهب بين كشف الحساب (Account.balance_*k، المصدر
الصحيح) وسجل SafeBoxTransaction (المستخدم في سند الصرف/بطاقة الخزنة).

بدل محاولة إعادة بناء القيود التاريخية (JE) واحدًا تلو الآخر - وهي محاولة
تتعارض مع Backfills يدوية سابقة (مثلاً 2026-04-15) أدت لنتائج غير متوقعة -
هذا السكربت يُنشئ حركة "تسوية" SafeBoxTransaction واحدة فقط لكل خزينة ذهب
ذات فرق، بحجم الفرق بالضبط (مُسجَّلة بالكامل في عيار 21k = العيار الرئيسي،
فلا حاجة لتحويل).

كل حركة تُسمّى بوضوح:
    ref_type = 'ledger_balance_adjustment'
    notes    = يحتوي تاريخ التنفيذ والفرق المُصحَّح، لتمييزها مستقبلاً عن أي
               حركة تشغيلية فعلية.

قبل أي --apply، يُكتب تقرير كامل (نص قابل للنسخ + ملف JSON في
backend/reports/) يحتوي: اسم الخزينة، الفرق قبل الإصلاح، الرصيد (سند الصرف)
قبل وبعد، وتاريخ التنفيذ.

تشغيل:
    docker cp backend/backfill_ledger_balance_adjustments.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/backfill_ledger_balance_adjustments.py            # dry run + تقرير
    docker exec yasargold-backend python backend/backfill_ledger_balance_adjustments.py --apply     # تطبيق فعلي + تقرير

الوضع الافتراضي: DRY RUN (لا يُحفظ شيء في قاعدة البيانات، لكن التقرير يُكتب دائمًا).
"""

import os
import sys
import json
import argparse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from sqlalchemy import func
from models import db, Account, SafeBox, SafeBoxTransaction
from routes import _account_weight_balance_main_karat, convert_to_main_karat


KARATS = ['18k', '21k', '22k', '24k']
REF_TYPE = 'ledger_balance_adjustment'
EPS = 0.0005


def ledger_balance_weight(safe_box_id: int):
    q = SafeBoxTransaction.query.filter_by(safe_box_id=safe_box_id)

    def _sum(field, direction):
        col = getattr(SafeBoxTransaction, field)
        return float(
            q.with_entities(func.coalesce(func.sum(col), 0.0))
            .filter(SafeBoxTransaction.direction == direction)
            .scalar() or 0.0
        )

    weight_main_karat = 0.0
    for k in KARATS:
        karat_num = int(k[:-1])
        w = _sum(f'weight_{k}', 'in') - _sum(f'weight_{k}', 'out')
        weight_main_karat += convert_to_main_karat(w, karat_num)
    return round(weight_main_karat, 6)


def run(apply: bool):
    with app.app_context():
        run_dt = datetime.now(timezone.utc)
        print(f"\n{'=' * 60}")
        print(f"{'تطبيق فعلي' if apply else 'DRY RUN — لن يُحفظ شيء في قاعدة البيانات'}")
        print(f"تاريخ التنفيذ: {run_dt.isoformat()}")
        print(f"{'=' * 60}\n")

        safe_boxes = [
            sb for sb in SafeBox.query.filter_by(safe_type='gold', is_active=True).all()
            if sb.account_id
        ]

        report_rows = []

        for sb in safe_boxes:
            acc = Account.query.get(sb.account_id)
            if not acc:
                continue

            stmt_weight = _account_weight_balance_main_karat(acc)
            led_before = ledger_balance_weight(sb.id)
            diff = round(stmt_weight - led_before, 6)

            if abs(diff) < EPS:
                continue

            direction = 'in' if diff > 0 else 'out'
            amount = abs(diff)
            led_after = round(led_before + diff, 6)

            row = {
                'safe_box_id': sb.id,
                'safe_box_name': sb.name,
                'account_id': sb.account_id,
                'statement_weight_main_karat': round(stmt_weight, 6),
                'ledger_weight_before': led_before,
                'ledger_weight_after': led_after,
                'diff_main_karat': diff,
                'adjustment_direction': direction,
                'adjustment_amount_weight_21k': round(amount, 6),
            }
            report_rows.append(row)

            print(f"[{sb.id:3}] {sb.name}")
            print(f"      الفرق قبل الإصلاح (كشف الحساب - سند الصرف) = {diff:>10,.3f}")
            print(f"      رصيد سند الصرف قبل  = {led_before:>10,.3f}")
            print(f"      رصيد سند الصرف بعد  = {led_after:>10,.3f}  (يطابق كشف الحساب = {stmt_weight:,.3f})")
            print(f"      حركة التسوية: direction={direction} weight_21k={amount:.6f}")
            print()

            if apply:
                tx = SafeBoxTransaction(
                    safe_box_id=sb.id,
                    ref_type=REF_TYPE,
                    ref_id=None,
                    invoice_id=None,
                    direction=direction,
                    amount_cash=0.0,
                    weight_18k=0.0,
                    weight_21k=round(amount, 6),
                    weight_22k=0.0,
                    weight_24k=0.0,
                    notes=(
                        f"تسوية تاريخية لرصيد الذهب (historical_gold_reconciliation) "
                        f"بتاريخ {run_dt.date().isoformat()} — "
                        f"الفرق المُصحَّح بين كشف الحساب وسند الصرف = {diff:+.3f} "
                        f"(عيار رئيسي 21k). هذه حركة محاسبية لتسوية الفروقات "
                        f"المتراكمة، وليست حركة تشغيلية فعلية."
                    ),
                    created_by='admin',
                )
                db.session.add(tx)

        # Always write the report (dry run or apply)
        reports_dir = os.path.join(os.path.dirname(__file__), 'reports')
        os.makedirs(reports_dir, exist_ok=True)
        report_path = os.path.join(
            reports_dir,
            f"safe_box_ledger_adjustments_{run_dt.strftime('%Y%m%dT%H%M%SZ')}"
            f"{'_applied' if apply else '_dryrun'}.json"
        )
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump({
                'run_at': run_dt.isoformat(),
                'applied': apply,
                'ref_type': REF_TYPE,
                'adjustments': report_rows,
            }, f, ensure_ascii=False, indent=2)

        print(f"\nتم كتابة التقرير: {report_path}")

        if apply:
            db.session.commit()
            print(f"\n✅ تم الحفظ. عدد حركات التسوية المُنشأة: {len(report_rows)}")
        else:
            db.session.rollback()
            print("\n(DRY RUN) لتطبيق التغييرات فعليًا أضف --apply")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    run(apply=args.apply)
