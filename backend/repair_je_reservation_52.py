"""
repair_je_reservation_52.py
============================
إصلاح قيد حجز مكتب شركة الجنية العربي رقم 52.

المشكلة:
--------
- قيد التسوية JE 4314 يحتوي على 16 سطراً:
    * سطران نقديان صحيحان: [17136] مشتريات و [17137] حساب المكتب
    * 14 سطراً خاطئة COGS (أزواج تكلفة مبيعات / مخزون كسر)
- قيد الإنشاء الوزني (إرسال ذهب للمكتب) مفقود تماماً

التصحيح:
---------
1. حذف السطور 17138-17151 من JE 4314 (إبقاء 17136 و17137 فقط)
2. إنشاء قيد إنشاء وزني جديد:
       Dr. موردو ذهب مشغول وزني (acc 889): debit_24k = 43.99
       Cr. مخزون الذهب ـ كسر وزني  (acc 762): credit_24k = 43.99

تشغيل:
------
    docker exec yasargold-backend python backend/repair_je_reservation_52.py
    docker exec yasargold-backend python backend/repair_je_reservation_52.py --apply
"""

import os
import sys
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, JournalEntry, JournalEntryLine

RESERVATION_ID = 52
RESERVATION_CODE = 'RES-20260616175502-0017'
OFFICE_NAME = 'شركة الجنية العربي'
SETTLEMENT_JE_ID = 4314
CASH_LINE_IDS_TO_KEEP = {17136, 17137}
WEIGHT_GRAMS = 43.99
KARAT = 24
RESERVATION_DATE = datetime(2026, 6, 16, 17, 50, 14)

INVENTORY_WEIGHT_ACC_ID = 762   # مخزون الذهب ـ كسر وزني (account_number=71310)
OFFICE_WEIGHT_ACC_ID = 889      # موردو ذهب مشغول وزني - شركة الجنية العربي


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

        print(f"── Reservation {RESERVATION_ID} ({RESERVATION_CODE}) ──")

        # ── 1. حذف السطور الخاطئة من قيد التسوية ──────────────────────────
        all_lines = JournalEntryLine.query.filter_by(
            journal_entry_id=SETTLEMENT_JE_ID
        ).all()

        lines_to_delete = [l for l in all_lines if l.id not in CASH_LINE_IDS_TO_KEEP]

        print(f"  JE {SETTLEMENT_JE_ID}: {len(all_lines)} سطر موجود")
        print(f"  سطور تُحذف: {len(lines_to_delete)} → {[l.id for l in lines_to_delete]}")
        print(f"  سطور تُبقى: {sorted(CASH_LINE_IDS_TO_KEEP)}")

        if apply:
            for line in lines_to_delete:
                db.session.delete(line)
            db.session.flush()
            print(f"  ✓ حُذفت {len(lines_to_delete)} سطر من JE {SETTLEMENT_JE_ID}")

        # ── 2. إنشاء قيد الإنشاء الوزني المفقود ────────────────────────────
        existing = JournalEntry.query.filter_by(
            reference_type='office_reservation',
            reference_id=RESERVATION_ID,
        ).filter(
            JournalEntry.entry_number.like('WGT-%')
        ).first()

        if existing:
            print(f"\n  ⚠ قيد وزني موجود بالفعل (JE {existing.id} {existing.entry_number}) — تخطي")
        else:
            entry_number = _next_wgt_number() if apply else 'WGT-2026-XXXXX'
            print(f"\n  إنشاء قيد وزني جديد: {entry_number}")
            print(f"    Dr. وزني المكتب (acc {OFFICE_WEIGHT_ACC_ID}): debit_{KARAT}k={WEIGHT_GRAMS}")
            print(f"    Cr. مخزون وزني  (acc {INVENTORY_WEIGHT_ACC_ID}): credit_{KARAT}k={WEIGHT_GRAMS}")

            if apply:
                create_je = JournalEntry(
                    entry_number=entry_number,
                    date=RESERVATION_DATE,
                    description=f'إرسال ذهب للحجز ({RESERVATION_CODE}) - مكتب {OFFICE_NAME}',
                    reference_type='office_reservation',
                    reference_id=RESERVATION_ID,
                    is_posted=True,
                    posted_at=RESERVATION_DATE,
                    posted_by='repair_script',
                )
                db.session.add(create_je)
                db.session.flush()

                debit_field = f'debit_{KARAT}k'
                credit_field = f'credit_{KARAT}k'

                db.session.add(JournalEntryLine(
                    journal_entry_id=create_je.id,
                    account_id=OFFICE_WEIGHT_ACC_ID,
                    description=f'ذهب بحيازة مكتب التسكير عيار {KARAT}',
                    **{debit_field: WEIGHT_GRAMS},
                ))
                db.session.add(JournalEntryLine(
                    journal_entry_id=create_je.id,
                    account_id=INVENTORY_WEIGHT_ACC_ID,
                    description=f'خروج ذهب كسر للتسكير عيار {KARAT}',
                    **{credit_field: WEIGHT_GRAMS},
                ))
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
