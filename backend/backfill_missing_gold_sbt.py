"""
backfill_missing_gold_sbt.py
=============================
ينشئ حركات SafeBoxTransaction (وزن فقط) المفقودة لقيود محاسبية محددة على
حساب خزينة ذهب، باستخدام نفس منطق /admin/sbt-create-from-je/<je_id>.

يُستخدم عندما يتطابق رصيد الوزن في كشف الحساب (Account.balance_*k) مع
بطاقة الخزنة/سند الصرف بسبب قيود (عادة office_reservation/voucher) لم تُولِّد
حركة SafeBoxTransaction وقت إنشائها.

تشغيل:
    cd backend
    python backfill_missing_gold_sbt.py --je-ids 3184,1424,1675            # dry run
    python backfill_missing_gold_sbt.py --je-ids 3184,1424,1675 --apply    # تطبيق فعلي

    أو في Docker:
    docker cp backend/backfill_missing_gold_sbt.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/backfill_missing_gold_sbt.py --je-ids 3184,1424,1675
    docker exec yasargold-backend python backend/backfill_missing_gold_sbt.py --je-ids 3184,1424,1675 --apply

الوضع الافتراضي: DRY RUN (لا يُحفظ شيء).
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, JournalEntry, SafeBox, SafeBoxTransaction


REF_TYPE = 'je_correction'
EPS = 0.001


def run(je_ids: list[int], apply: bool):
    with app.app_context():
        print(f"\n{'=' * 55}")
        print(f"{'تطبيق فعلي' if apply else 'DRY RUN — لن يُحفظ شيء'}")
        print(f"{'=' * 55}\n")

        for je_id in je_ids:
            je = JournalEntry.query.get(je_id)
            if not je:
                print(f"JE {je_id}: غير موجود — تجاهل")
                continue
            if not getattr(je, 'is_posted', False):
                print(f"JE {je_id}: غير مرحل — تجاهل")
                continue

            existing = SafeBoxTransaction.query.filter_by(ref_type=REF_TYPE, ref_id=je_id).first()
            if existing:
                print(f"JE {je_id}: يوجد SBT مسبقًا (#{existing.id}) — تجاهل")
                continue

            lines = [l for l in (je.lines or []) if not getattr(l, 'is_deleted', False)]
            acc_ids = list({int(l.account_id) for l in lines if l.account_id is not None})

            safe_by_acc = {}
            for sb in SafeBox.query.filter(
                SafeBox.account_id.in_(acc_ids),
                SafeBox.safe_type == 'gold',
                SafeBox.is_active == True,
            ).all():
                if sb.account_id is not None:
                    safe_by_acc[int(sb.account_id)] = sb

            if not safe_by_acc:
                print(f"JE {je_id}: لا توجد خزائن ذهب مرتبطة بحسابات هذا القيد — تجاهل")
                continue

            for line in lines:
                sb = safe_by_acc.get(int(line.account_id))
                if not sb:
                    continue
                for direction, w18, w21, w22, w24 in [
                    ('in',  float(line.debit_18k or 0), float(line.debit_21k or 0), float(line.debit_22k or 0), float(line.debit_24k or 0)),
                    ('out', float(line.credit_18k or 0), float(line.credit_21k or 0), float(line.credit_22k or 0), float(line.credit_24k or 0)),
                ]:
                    if not any(v > EPS for v in (w18, w21, w22, w24)):
                        continue
                    print(f"JE {je_id} -> safe_box [{sb.id}] {sb.name}: "
                          f"direction={direction} w18={w18:.3f} w21={w21:.3f} w22={w22:.3f} w24={w24:.3f}")
                    if apply:
                        tx = SafeBoxTransaction(
                            safe_box_id=sb.id,
                            ref_type=REF_TYPE,
                            ref_id=je_id,
                            direction=direction,
                            amount_cash=0.0,
                            weight_18k=round(w18, 6),
                            weight_21k=round(w21, 6),
                            weight_22k=round(w22, 6),
                            weight_24k=round(w24, 6),
                            notes=f'JE {getattr(je, "entry_number", je_id)} correction (backfill)',
                            created_by='admin',
                        )
                        db.session.add(tx)

        if apply:
            db.session.commit()
            print("\n✅ تم الحفظ.")
        else:
            db.session.rollback()
            print("\n(DRY RUN) لتطبيق التغييرات فعليًا أضف --apply")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--je-ids', type=str, required=True, help='قائمة JE ids مفصولة بفواصل')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    je_ids = [int(x.strip()) for x in args.je_ids.split(',') if x.strip()]
    run(je_ids, apply=args.apply)
