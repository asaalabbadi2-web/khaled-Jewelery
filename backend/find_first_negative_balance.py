"""
find_first_negative_balance.py
=================================
قراءة فقط بالكامل. يبحث عن أول لحظة تاريخية حقيقية (بترتيب created_at
الحقيقي لكل سند، لا حقل date القابل للتقديم بأثر رجعي للسندات التلقائية)
نزل فيها الرصيد الفعلي لحساب مقاصة معيّن تحت الصفر — وهو ما يُفترض أن
الحارس insufficient_clearing_balance في _create_clearing_settlement_voucher
يمنعه دائماً.

لكل سطر حساب (VoucherAccountLine) على هذا الحساب، يجلب created_at الحقيقي
للسند الأب (لا تاريخ السند date)، يرتّب زمنياً بدقة، ويعيد بناء الرصيد
الجاري الحقيقي. عند أول نزول تحت الصفر، يطبع تفاصيل كاملة عن السند
المسؤول (نوعه، مُنشئه، مبلغه، ما كان متاحاً فعلياً قبل لحظة إنشائه بالضبط)
ليُحدَّد بدقة هل الحارس فشل، أم تم تجاوزه عبر مسار آخر.

لا يُعدّل أي بيانات.

تشغيل:
    docker cp backend/find_first_negative_balance.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/find_first_negative_balance.py --account-id 777
"""

import os
import sys
import json
import argparse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, VoucherAccountLine, Voucher


def run(account_id: int):
    with app.app_context():
        run_dt = datetime.now(timezone.utc)

        rows = (
            db.session.query(VoucherAccountLine, Voucher)
            .join(Voucher, Voucher.id == VoucherAccountLine.voucher_id)
            .filter(VoucherAccountLine.account_id == account_id)
            .all()
        )
        print(f"عدد سطور الحساب: {len(rows)}")

        # رتّب بـ created_at الحقيقي للسند الأب (fallback لتاريخ السطر نفسه إن غاب)
        def sort_key(pair):
            line, voucher = pair
            ts = voucher.created_at or line.created_at or voucher.date
            return ts

        rows_sorted = sorted(rows, key=sort_key)

        running = 0.0
        min_running = 0.0
        first_negative = None
        negative_events = []
        for line, voucher in rows_sorted:
            ts = voucher.created_at or line.created_at or voucher.date
            amount = float(line.amount or 0.0)
            prev_running = running
            if line.line_type == 'debit':
                running = round(running + amount, 2)
            else:
                running = round(running - amount, 2)

            if running < min_running:
                min_running = running

            if prev_running >= -0.01 and running < -0.01:
                event = {
                    'voucher_id': voucher.id,
                    'voucher_number': voucher.voucher_number,
                    'voucher_type': voucher.voucher_type,
                    'status': voucher.status,
                    'created_by': voucher.created_by,
                    'created_at_used_for_sort': ts.isoformat() if hasattr(ts, 'isoformat') else str(ts),
                    'voucher_date': voucher.date.isoformat() if voucher.date else None,
                    'line_type': line.line_type,
                    'line_amount': amount,
                    'available_before': prev_running,
                    'running_after': running,
                    'shortfall': round(amount - max(prev_running, 0.0), 2) if line.line_type == 'credit' else None,
                    'description': line.description,
                    'reference_type': voucher.reference_type,
                    'reference_number': voucher.reference_number,
                }
                negative_events.append(event)
                if first_negative is None:
                    first_negative = event

        print(f"\nأدنى رصيد وصل إليه الحساب عبر كل التاريخ (بترتيب created_at الحقيقي): {min_running:.2f}")
        print(f"الرصيد النهائي (يجب أن يطابق الرصيد الفعلي المعروض في النظام): {running:.2f}")

        print(f"\nعدد لحظات العبور من موجب/صفر إلى سالب: {len(negative_events)}")
        for ev in negative_events[:30]:
            print(f"  {ev['created_at_used_for_sort']} | {ev['voucher_number']} (id={ev['voucher_id']}, "
                  f"status={ev['status']}, created_by={ev['created_by']}) | "
                  f"متاح_قبل={ev['available_before']:.2f} | بعد={ev['running_after']:.2f} | "
                  f"{ev['description'][:70] if ev['description'] else ''}")

        if first_negative:
            print("\n" + "=" * 70)
            print("أول لحظة نزل فيها الرصيد تحت الصفر فعلياً:")
            print("=" * 70)
            print(json.dumps(first_negative, ensure_ascii=False, indent=2, default=str))

        report = {
            'generated_at': run_dt.isoformat(),
            'account_id': account_id,
            'min_balance_ever': min_running,
            'final_balance': running,
            'negative_crossing_events': negative_events,
        }
        reports_dir = os.path.join(os.path.dirname(__file__), 'reports')
        os.makedirs(reports_dir, exist_ok=True)
        path = os.path.join(
            reports_dir,
            f"find_first_negative_balance_acc{account_id}_{run_dt.strftime('%Y%m%dT%H%M%SZ')}.json",
        )
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        print(f"\nتم كتابة التقرير: {path}")
        print("(قراءة فقط بالكامل)")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--account-id', type=int, default=777)
    args = parser.parse_args()
    run(account_id=args.account_id)
