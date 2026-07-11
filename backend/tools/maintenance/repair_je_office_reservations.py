"""
repair_je_office_reservations.py
=================================
إصلاح قيود حجزَي مكتب شركة الجنية العربي (reservation 48 و 49).

المشكلة:
--------
- قيدا التسوية (JE 3830, 3831) يحتويان على:
    * سطور COGS خاطئة (تكلفة مبيعات - حساب 521)
    * سطور وزنية خاطئة (الذهب يرجع من المكتب — لكن هذا يجب أن يحدث بشكل منفصل)
- قيود الإنشاء الوزنية (إرسال ذهب للمكتب) مفقودة

التصحيح:
---------
1. حذف السطور الخاطئة من JE 3830 و JE 3831 (يُبقى فقط السطرين النقديين)
2. إنشاء قيدَي إنشاء وزنيين مفقودين لكلا الحجزين

تشغيل:
------
    cd backend
    source venv/bin/activate
    python repair_je_office_reservations.py          # dry run — لا يُحفظ شيء
    python repair_je_office_reservations.py --apply  # تطبيق فعلي
"""

import os
import sys
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, JournalEntry, JournalEntryLine

# ─── بيانات الحجزين ────────────────────────────────────────────────────────

RESERVATIONS = [
    {
        'reservation_id': 48,
        'reservation_code': 'RES-20260610183402-0013',
        'office_name': 'شركة الجنية العربي',
        'settlement_je_id': 3830,
        'cash_line_ids_to_keep': [15419, 15421],   # مشتريات + حساب المكتب فقط
        'weight_grams': 650.0,
        'karat': 24,
        'reservation_date': datetime(2026, 6, 10, 18, 34, 2),
    },
    {
        'reservation_id': 49,
        'reservation_code': 'RES-20260610183552-0014',
        'office_name': 'شركة الجنية العربي',
        'settlement_je_id': 3831,
        'cash_line_ids_to_keep': [15541, 15543],   # مشتريات + حساب المكتب فقط
        'weight_grams': 108.8,
        'karat': 24,
        'reservation_date': datetime(2026, 6, 10, 18, 35, 52),
    },
    {
        'reservation_id': 51,
        'reservation_code': 'RES-20260611224726-0016',
        'office_name': 'شركة الجنية العربي',
        'settlement_je_id': 3890,
        'cash_line_ids_to_keep': [15801, 15802],   # مشتريات + حساب المكتب فقط
        'weight_grams': 350.0,
        'karat': 24,
        'reservation_date': datetime(2026, 6, 11, 19, 47, 26),
    },
]

# حساب وزني المخزون (مخزون الذهب ـ كسر وزني)
INVENTORY_WEIGHT_ACC_ID = 762
# حساب وزني المكتب (موردو ذهب مشغول وزني - شركة الجنية العربي)
OFFICE_WEIGHT_ACC_ID = 889


def _next_wgt_number() -> str:
    last = (
        JournalEntry.query
        .filter(JournalEntry.entry_number.like('WGT-%'))
        .order_by(JournalEntry.id.desc())
        .first()
    )
    if last and last.entry_number:
        try:
            seq = int(last.entry_number.split('-')[-1]) + 1
            return f'WGT-2026-{seq:05d}'
        except Exception:
            pass
    return 'WGT-2026-99001'


def run(apply: bool):
    with app.app_context():
        print(f"\n{'=' * 60}")
        print(f"{'تطبيق فعلي' if apply else 'DRY RUN — لن يُحفظ شيء'}")
        print(f"{'=' * 60}\n")

        for res in RESERVATIONS:
            res_id = res['reservation_id']
            je_id = res['settlement_je_id']
            keep_ids = set(res['cash_line_ids_to_keep'])
            code = res['reservation_code']
            karat = res['karat']
            weight = res['weight_grams']
            date = res['reservation_date']

            print(f"── Reservation {res_id} ({code}) ──")

            # ── 1. حذف السطور الخاطئة من قيد التسوية ──────────────────────
            all_lines = JournalEntryLine.query.filter_by(
                journal_entry_id=je_id
            ).all()

            lines_to_delete = [l for l in all_lines if l.id not in keep_ids]
            print(f"  JE {je_id}: {len(all_lines)} سطر موجود")
            print(f"  سطور تُحذف: {len(lines_to_delete)}")
            print(f"  سطور تُبقى:  {len(keep_ids)}")

            if apply:
                for line in lines_to_delete:
                    db.session.delete(line)
                db.session.flush()
                print(f"  ✓ حُذفت {len(lines_to_delete)} سطر من JE {je_id}")

            # ── 2. إنشاء قيد الإنشاء الوزني المفقود ────────────────────────
            existing_create_je = JournalEntry.query.filter_by(
                reference_type='office_reservation',
                reference_id=res_id,
                description=f'إرسال ذهب للحجز ({code}) - مكتب {res["office_name"]}',
            ).first()

            if existing_create_je:
                print(f"  ⚠ قيد الإنشاء موجود بالفعل (JE {existing_create_je.id}) — تخطي")
            else:
                entry_number = _next_wgt_number() if apply else 'WGT-2026-XXXXX'
                print(f"  إنشاء قيد وزني جديد: {entry_number}")
                print(f"    Dr. وزني المكتب (acc {OFFICE_WEIGHT_ACC_ID}): debit_{karat}k={weight}")
                print(f"    Cr. مخزون وزني   (acc {INVENTORY_WEIGHT_ACC_ID}): credit_{karat}k={weight}")

                if apply:
                    create_je = JournalEntry(
                        entry_number=entry_number,
                        date=date,
                        description=f'إرسال ذهب للحجز ({code}) - مكتب {res["office_name"]}',
                        reference_type='office_reservation',
                        reference_id=res_id,
                        is_posted=True,
                        posted_at=date,
                        posted_by='repair_script',
                    )
                    db.session.add(create_je)
                    db.session.flush()

                    karat_field = f'debit_{karat}k'
                    karat_field_cr = f'credit_{karat}k'

                    # مدين: وزني المكتب
                    dr_line = JournalEntryLine(
                        journal_entry_id=create_je.id,
                        account_id=OFFICE_WEIGHT_ACC_ID,
                        description=f'ذهب بحيازة مكتب التسكير عيار {karat}',
                        **{karat_field: weight},
                    )
                    db.session.add(dr_line)

                    # دائن: مخزون وزني
                    cr_line = JournalEntryLine(
                        journal_entry_id=create_je.id,
                        account_id=INVENTORY_WEIGHT_ACC_ID,
                        description=f'خروج ذهب كسر للتسكير عيار {karat}',
                        **{karat_field_cr: weight},
                    )
                    db.session.add(cr_line)
                    db.session.flush()

                    print(f"  ✓ أُنشئ قيد الإنشاء WGT: JE {create_je.id} ({entry_number})")

            print()

        if apply:
            db.session.commit()
            print("✅ تم الحفظ بنجاح.")
        else:
            db.session.rollback()
            print("ℹ️  DRY RUN انتهى — لم يُحفظ شيء. مرر --apply للتطبيق الفعلي.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='تطبيق التغييرات فعلياً')
    args = parser.parse_args()
    run(apply=args.apply)
