"""
audit_clearing_accounts_reference_types.py
=============================================
قراءة فقط بالكامل. تدقيق المرحلة 2: يحصر كل أنواع reference_type التي تلمس
فعلياً أي حساب تابع لصندوق safe_type='clearing' (مدى، تابي، تمارا،
فيزا/ماستر، أو أي حساب مقاصة آخر يُضاف مستقبلاً) — لا حساب واحد محدّد.

لكل حساب مقاصة، ولكل reference_type ظهر عليه، يطبع: العدد، إجمالي المدين،
إجمالي الدائن، ومثالاً واحداً (وصف + تاريخ) لأقدم وأحدث سطر من ذلك النوع،
لتسهيل تصنيف كل نوع (تابع لمحرّك التسوية / تسوية بنكية مشروعة / يحتاج
مراجعة) قبل بناء القائمة البيضاء النهائية لمرحلة 2.

لا يُعدّل أي بيانات.

تشغيل:
    docker cp backend/audit_clearing_accounts_reference_types.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/audit_clearing_accounts_reference_types.py
"""

import os
import sys
import json
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, SafeBox, JournalEntry, JournalEntryLine, _KNOWN_CLEARING_REFERENCE_TYPES


def _db_has_column(table, column):
    try:
        from sqlalchemy import inspect as sa_inspect
        inspector = sa_inspect(db.engine)
        cols = [c['name'] for c in inspector.get_columns(table)]
        return column in cols
    except Exception:
        return False


def run():
    with app.app_context():
        run_dt = datetime.now(timezone.utc)

        clearing_safe_boxes = SafeBox.query.filter_by(safe_type='clearing').all()
        if not clearing_safe_boxes:
            print("لا يوجد أي صندوق safe_type='clearing' في هذه القاعدة.")
            return

        print(f"عدد صناديق المقاصة: {len(clearing_safe_boxes)}")
        for sb in clearing_safe_boxes:
            print(f"  - {sb.name} (safe_box_id={sb.id}, account_id={sb.account_id})")
        print()

        account_ids = [sb.account_id for sb in clearing_safe_boxes if sb.account_id]
        account_name_by_id = {sb.account_id: sb.name for sb in clearing_safe_boxes}

        filters = [
            JournalEntryLine.account_id.in_(account_ids),
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
        print(f"إجمالي سطور القيود على كل حسابات المقاصة: {len(rows)}\n")

        # bucket[account_id][reference_type] = {...}
        buckets = defaultdict(lambda: defaultdict(lambda: {
            'count': 0, 'debit': 0.0, 'credit': 0.0,
            'earliest': None, 'latest': None,
            'sample_description': None,
        }))

        for line, entry in rows:
            ref = entry.reference_type or '(NULL — غير مصنَّف)'
            b = buckets[line.account_id][ref]
            b['count'] += 1
            b['debit'] += float(line.cash_debit or 0.0)
            b['credit'] += float(line.cash_credit or 0.0)
            d = entry.date
            if b['earliest'] is None or (d and d < b['earliest']):
                b['earliest'] = d
            if b['latest'] is None or (d and d > b['latest']):
                b['latest'] = d
                b['sample_description'] = line.description or entry.description

        report = {'generated_at': run_dt.isoformat(), 'accounts': {}}

        for account_id in account_ids:
            name = account_name_by_id.get(account_id, '?')
            print("=" * 70)
            print(f"حساب: {name} (account_id={account_id})")
            print("=" * 70)
            acc_buckets = buckets.get(account_id, {})
            if not acc_buckets:
                print("  (لا توجد حركات)")
                continue
            acc_report = []
            for ref, b in sorted(acc_buckets.items(), key=lambda kv: -kv[1]['count']):
                net = round(b['debit'] - b['credit'], 2)
                if 'NULL' in ref:
                    flag = '  ⚠️ يحتاج مراجعة (غير مصنَّف)'
                elif ref not in _KNOWN_CLEARING_REFERENCE_TYPES:
                    flag = '  ⚠️ خارج القائمة المعروفة حالياً (مرحلة 2 — راجع قبل الترقية لمرحلة 3)'
                else:
                    flag = ''
                print(f"  {ref:30s} | عدد={b['count']:4d} | مدين={b['debit']:12.2f} | "
                      f"دائن={b['credit']:12.2f} | صافي={net:12.2f}{flag}")
                print(f"      آخر مثال ({b['latest']}): {(b['sample_description'] or '')[:90]}")
                acc_report.append({
                    'reference_type': ref,
                    'count': b['count'],
                    'debit': round(b['debit'], 2),
                    'credit': round(b['credit'], 2),
                    'net': net,
                    'earliest': b['earliest'].isoformat() if b['earliest'] else None,
                    'latest': b['latest'].isoformat() if b['latest'] else None,
                    'sample_description': b['sample_description'],
                })
            report['accounts'][str(account_id)] = {'name': name, 'reference_types': acc_report}
            print()

        reports_dir = os.path.join(os.path.dirname(__file__), 'reports')
        os.makedirs(reports_dir, exist_ok=True)
        path = os.path.join(
            reports_dir,
            f"audit_clearing_accounts_reference_types_{run_dt.strftime('%Y%m%dT%H%M%SZ')}.json",
        )
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        print(f"تم كتابة التقرير الكامل: {path}")
        print("(قراءة فقط بالكامل)")


if __name__ == '__main__':
    run()
