"""
find_first_negative_balance.py
=================================
قراءة فقط بالكامل. يبحث عن أول لحظة تاريخية حقيقية نزل فيها الرصيد الفعلي
لحساب معيّن تحت الصفر — وهو ما يُفترض أن الحارس insufficient_clearing_balance
في _create_clearing_settlement_voucher يمنعه دائماً.

يقرأ من JournalEntryLine مباشرة (المصدر نفسه الذي يستخدمه endpoint كشف
الحساب /api/accounts/<id>/statement، بنفس فلاتر is_deleted/is_posted
تماماً، لضمان مطابقة العدد الكامل للسطور) — لكن يرتّب بـ
JournalEntry.created_at الحقيقي (لا JournalEntry.date القابل للتقديم
بأثر رجعي للسندات التلقائية، الذي يستخدمه كشف الحساب نفسه للعرض).

عند أول نزول تحت الصفر، يطبع تفاصيل كاملة عن القيد المسؤول.

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
from models import db, JournalEntry, JournalEntryLine


def _db_has_column(table, column):
    try:
        from sqlalchemy import inspect as sa_inspect
        inspector = sa_inspect(db.engine)
        cols = [c['name'] for c in inspector.get_columns(table)]
        return column in cols
    except Exception:
        return False


def run(account_id: int):
    with app.app_context():
        run_dt = datetime.now(timezone.utc)

        filters = [
            JournalEntryLine.account_id == account_id,
            JournalEntry.is_deleted == False,
            JournalEntryLine.is_deleted == False,
        ]
        if _db_has_column('journal_entry', 'is_posted'):
            filters.append(JournalEntry.is_posted == True)

        rows = (
            db.session.query(JournalEntryLine, JournalEntry)
            .join(JournalEntry, JournalEntry.id == JournalEntryLine.journal_entry_id)
            .filter(*filters)
            .all()
        )
        print(f"عدد سطور القيود (نفس فلاتر كشف الحساب): {len(rows)}")

        # رتّب بـ created_at الحقيقي للقيد، لا date القابل للتقديم بأثر رجعي
        rows_sorted = sorted(
            rows,
            key=lambda pair: pair[1].created_at or pair[1].date,
        )

        running = 0.0
        min_running = 0.0
        first_negative = None
        negative_events = []
        for line, entry in rows_sorted:
            debit = float(line.cash_debit or 0.0)
            credit = float(line.cash_credit or 0.0)
            prev_running = running
            running = round(running + debit - credit, 2)

            if running < min_running:
                min_running = running

            if prev_running >= -0.01 and running < -0.01:
                ts = entry.created_at or entry.date
                event = {
                    'journal_entry_id': entry.id,
                    'entry_number': entry.entry_number,
                    'reference_type': entry.reference_type,
                    'reference_id': entry.reference_id,
                    'reference_number': entry.reference_number,
                    'created_by': entry.created_by,
                    'created_at_used_for_sort': ts.isoformat() if hasattr(ts, 'isoformat') else str(ts),
                    'entry_date_field': entry.date.isoformat() if entry.date else None,
                    'line_id': line.id,
                    'line_description': line.description,
                    'cash_debit': debit,
                    'cash_credit': credit,
                    'available_before': prev_running,
                    'running_after': running,
                }
                negative_events.append(event)
                if first_negative is None:
                    first_negative = event

        print(f"\nأدنى رصيد وصل إليه الحساب عبر كل التاريخ (بترتيب created_at الحقيقي): {min_running:.2f}")
        print(f"الرصيد النهائي المُعاد بناؤه (يجب أن يطابق الرصيد الفعلي المعروض في النظام): {running:.2f}")

        print(f"\nعدد لحظات العبور من موجب/صفر إلى سالب: {len(negative_events)}")
        for ev in negative_events[:30]:
            print(f"  {ev['created_at_used_for_sort']} | JE#{ev['journal_entry_id']} ({ev['entry_number']}, "
                  f"ref={ev['reference_type']}#{ev['reference_id']}, created_by={ev['created_by']}) | "
                  f"متاح_قبل={ev['available_before']:.2f} | بعد={ev['running_after']:.2f} | "
                  f"debit={ev['cash_debit']:.2f} credit={ev['cash_credit']:.2f} | {ev['line_description'] or ''}")

        if first_negative:
            print("\n" + "=" * 70)
            print("أول لحظة نزل فيها الرصيد تحت الصفر فعلياً:")
            print("=" * 70)
            print(json.dumps(first_negative, ensure_ascii=False, indent=2, default=str))

        report = {
            'generated_at': run_dt.isoformat(),
            'account_id': account_id,
            'line_count': len(rows),
            'min_balance_ever': min_running,
            'final_balance_reconstructed': running,
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
