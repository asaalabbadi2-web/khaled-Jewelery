"""
backfill_all_missing_gold_sbt.py
==================================
حل جذري شامل: يفحص كل خزائن الذهب النشطة، ولكل قيد محاسبي مرحّل (posted،
غير محذوف) له أثر على وزن حساب الخزينة ولا يوجد له أي SafeBoxTransaction
(بأي ref_type)، يُنشئ حركة SafeBoxTransaction مطابقة — بنفس منطق
/admin/sbt-create-from-je ونفس منطق backfill_missing_gold_sbt.py، لكن
لكل الخزائن دفعة واحدة بدل خزينة بخزينة.

بعد التطبيق، يجب أن يتطابق وزن "بطاقة الخزنة"/سند الصرف مع كشف الحساب
لكل خزائن الذهب.

تشغيل:
    cd backend
    python backfill_all_missing_gold_sbt.py            # dry run
    python backfill_all_missing_gold_sbt.py --apply    # تطبيق فعلي

    أو في Docker:
    docker cp backend/backfill_all_missing_gold_sbt.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/backfill_all_missing_gold_sbt.py
    docker exec yasargold-backend python backend/backfill_all_missing_gold_sbt.py --apply

الوضع الافتراضي: DRY RUN (لا يُحفظ شيء).
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, SafeBox, JournalEntry, JournalEntryLine, SafeBoxTransaction
from routes import convert_to_main_karat


REF_TYPE = 'je_correction'
EPS = 0.0005


def run(apply: bool):
    with app.app_context():
        print(f"\n{'=' * 55}")
        print(f"{'تطبيق فعلي' if apply else 'DRY RUN — لن يُحفظ شيء'}")
        print(f"{'=' * 55}\n")

        safe_boxes = [
            sb for sb in SafeBox.query.filter_by(safe_type='gold', is_active=True).all()
            if sb.account_id
        ]

        total_created = 0

        for sb in safe_boxes:
            lines = (
                JournalEntryLine.query
                .join(JournalEntry)
                .filter(
                    JournalEntryLine.account_id == sb.account_id,
                    JournalEntry.is_deleted == False,
                    JournalEntryLine.is_deleted == False,
                    JournalEntry.is_posted == True,
                    JournalEntry.is_draft == False,
                )
                .all()
            )

            missing = []
            for line in lines:
                entry = line.journal_entry
                w18 = (line.debit_18k or 0) - (line.credit_18k or 0)
                w21 = (line.debit_21k or 0) - (line.credit_21k or 0)
                w22 = (line.debit_22k or 0) - (line.credit_22k or 0)
                w24 = (line.debit_24k or 0) - (line.credit_24k or 0)
                if not any(abs(v) > EPS for v in (w18, w21, w22, w24)):
                    continue

                already = SafeBoxTransaction.query.filter_by(
                    safe_box_id=sb.id, ref_id=entry.id
                ).count()
                if already:
                    continue

                missing.append((entry, line, w18, w21, w22, w24))

            if not missing:
                continue

            net_main_karat = sum(
                convert_to_main_karat(w18, 18) + convert_to_main_karat(w21, 21)
                + convert_to_main_karat(w22, 22) + convert_to_main_karat(w24, 24)
                for (_, _, w18, w21, w22, w24) in missing
            )

            print(f"[{sb.id}] {sb.name}: {len(missing)} قيد بلا SBT — صافي الفرق = {net_main_karat:,.3f} (عيار رئيسي)")

            for entry, line, w18, w21, w22, w24 in missing:
                for direction, dw18, dw21, dw22, dw24 in [
                    ('in',  max(w18, 0), max(w21, 0), max(w22, 0), max(w24, 0)),
                    ('out', max(-w18, 0), max(-w21, 0), max(-w22, 0), max(-w24, 0)),
                ]:
                    if not any(v > EPS for v in (dw18, dw21, dw22, dw24)):
                        continue
                    print(f"    JE {entry.id} ({getattr(entry, 'reference_type', None) or 'manual'}, "
                          f"{getattr(entry, 'entry_number', None)}): {direction} "
                          f"w18={dw18:.3f} w21={dw21:.3f} w22={dw22:.3f} w24={dw24:.3f}")
                    if apply:
                        tx = SafeBoxTransaction(
                            safe_box_id=sb.id,
                            ref_type=REF_TYPE,
                            ref_id=entry.id,
                            direction=direction,
                            amount_cash=0.0,
                            weight_18k=round(dw18, 6),
                            weight_21k=round(dw21, 6),
                            weight_22k=round(dw22, 6),
                            weight_24k=round(dw24, 6),
                            notes=f'JE {getattr(entry, "entry_number", entry.id)} correction (backfill-all)',
                            created_by='admin',
                        )
                        db.session.add(tx)
                        total_created += 1

        if apply:
            db.session.commit()
            print(f"\n✅ تم الحفظ. عدد الحركات المُنشأة: {total_created}")
        else:
            db.session.rollback()
            print("\n(DRY RUN) لتطبيق التغييرات فعليًا أضف --apply")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    run(apply=args.apply)
