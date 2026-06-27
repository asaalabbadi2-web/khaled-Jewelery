"""
fix_duplicate_safebox_transactions_from_backfill.py
=====================================================
يصحّح خطأ ارتكبه fix_voucher_safebox_transactions_and_posting.py (شُغِّل على
الإنتاج بـ--apply، رحّل/أعاد بناء 1055 قيداً): _rebuild_safe_box_transactions_for_journal_entry
تحذف فقط سطور SafeBoxTransaction التي ref_type='journal_entry' قبل إعادة
البناء. اكتشفنا بعد التشغيل أن **كل** سندات (voucher) كانت أصلاً مغطّاة منذ
إنشائها الأصلي بدالة منفصلة موجودة سلفاً (_append_safe_transactions_for_voucher
-- تُستدعى من 11 موضعاً مختلفاً، فيها حارس idempotency خاص بـ
ref_type='voucher'). فكل سطر "journal_entry" أضافه السكريبت لقيد مصدره سند هو
**تكرار مؤكَّد بنسبة 100%** -- تأكَّد بتتبّع كل سندات تحويل خزينة موظف واحد
(يوسف الشعبي، AV-2026-00037 إلى 00206) ووجود سطر 'voucher' سليم لكل واحد منها
من يوم اعتماده الأصلي.

أما حجوزات المكاتب (office_reservation) فلا توجد دالة مكافئة لها -- معظم ما
أضافه السكريبت لها تصحيح حقيقي ومطلوب (مثال مؤكَّد: قيد "إرسال ذهب للحجز"
WGT-2026-00023 لمكتب "تسكير فورية وأشخاص" كان ناقصاً فعلاً). الاستثناء: حالات
معدودة كانت مغطّاة من قبل بتصحيح تاريخي أقدم منفصل (ملاحَظ بنص notes يحوي
"backfill: GL orphan je_id=...").

المنطق (تتبّع مرجعي دقيق، لا مطابقة قيم -- المحاولة الأولى بمطابقة القيم كانت
خاطئة: حذفت سطراً جديداً شرعياً ظنّاً أنه يطابق سطراً آخر بالمصادفة في القيمة):

  1. لكل سطر SafeBoxTransaction غير 'journal_entry'، نحاول تحديد معرّف القيد
     المحاسبي (journal_entry_id) الحقيقي الذي يمثّله:
       - ref_type='voucher'  -> Voucher.query.get(ref_id).journal_entry_id
       - ref_type='office_reservation' و notes فيها "je_id=NUMBER" -> نفس الرقم
       - غير ذلك -> لا نستطيع التأكد، يُتجاهل (لا يُستخدم للمطابقة أبداً)
  2. نبني مجموعة كل journal_entry_id المغطّى فعلاً بسطر غير 'journal_entry'.
  3. كل سطر ref_type='journal_entry' معرّفه (ref_id = journal_entry_id) موجود
     في تلك المجموعة = تكرار مؤكَّد -> يُحذف.
  4. كل سطر ref_type='journal_entry' غير موجود في المجموعة = تصحيح حقيقي
     (الحالة التي صمّم السكريبت السابق لأجلها) -> يبقى كما هو، لا يُلمَس.

لا توجد هنا أي مطابقة بالقيمة (مبلغ/وزن) -- المطابقة بالمرجع الفعلي فقط، فلا
خطر تكرار غلطة "حذف سطر شرعي بالمصادفة".

الوضع الافتراضي: DRY RUN. --apply للتنفيذ.

تشغيل:
    docker cp backend/fix_duplicate_safebox_transactions_from_backfill.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/fix_duplicate_safebox_transactions_from_backfill.py            # dry run
    docker exec yasargold-backend python backend/fix_duplicate_safebox_transactions_from_backfill.py --apply    # تنفيذ فعلي
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, SafeBox, SafeBoxTransaction, Voucher

_JE_ID_IN_NOTES = re.compile(r'je_id=(\d+)')


def run(apply: bool) -> None:
    with app.app_context():
        all_tx = SafeBoxTransaction.query.all()

        je_rows = [tx for tx in all_tx if (tx.ref_type or '').strip().lower() == 'journal_entry']
        other_rows = [tx for tx in all_tx if (tx.ref_type or '').strip().lower() != 'journal_entry']

        covered_je_ids = set()
        voucher_ids_needed = {
            int(tx.ref_id) for tx in other_rows
            if (tx.ref_type or '').strip().lower() == 'voucher' and tx.ref_id is not None
        }
        vouchers_by_id = {
            v.id: v for v in Voucher.query.filter(Voucher.id.in_(voucher_ids_needed)).all()
        } if voucher_ids_needed else {}

        for tx in other_rows:
            rt = (tx.ref_type or '').strip().lower()
            if rt == 'voucher' and tx.ref_id is not None:
                voucher = vouchers_by_id.get(int(tx.ref_id))
                if voucher and voucher.journal_entry_id:
                    covered_je_ids.add(int(voucher.journal_entry_id))
            elif rt == 'office_reservation':
                m = _JE_ID_IN_NOTES.search(tx.notes or '')
                if m:
                    covered_je_ids.add(int(m.group(1)))

        to_delete = [tx for tx in je_rows if tx.ref_id is not None and int(tx.ref_id) in covered_je_ids]
        to_keep = [tx for tx in je_rows if tx not in to_delete]

        print(f"سطور SafeBoxTransaction الكلية: {len(all_tx)}")
        print(f"سطور بنوع مرجع journal_entry (كلها من السكريبت السابق): {len(je_rows)}")
        print(f"  منها مكرَّرة (لها سطر أصلي موثَّق بمرجع آخر) -> ستُحذف: {len(to_delete)}")
        print(f"  منها تصحيح حقيقي (لا يوجد سطر أصلي لها) -> تبقى: {len(to_keep)}\n")

        affected_safe_boxes = sorted({tx.safe_box_id for tx in to_delete})
        safe_names = {sb.id: sb.name for sb in SafeBox.query.filter(SafeBox.id.in_(affected_safe_boxes)).all()}
        for sb_id in affected_safe_boxes:
            count = sum(1 for tx in to_delete if tx.safe_box_id == sb_id)
            print(f"  - خزينة #{sb_id} ({safe_names.get(sb_id, '?')}): {count} سطراً مكرَّراً سيُحذف")

        print(f"\nسطور 'تصحيح حقيقي' ستبقى (نموذج، أول 20):")
        for tx in to_keep[:20]:
            print(f"  - SBT#{tx.id} safe={tx.safe_box_id} ref_id(je)={tx.ref_id} {tx.notes}")
        if len(to_keep) > 20:
            print(f"  ... و{len(to_keep) - 20} غيرها")

        if not apply:
            print("\n(DRY RUN) لتطبيق التغيير فعليًا أضف --apply")
            return

        for tx in to_delete:
            db.session.delete(tx)
        db.session.commit()
        print(f"\nتم حذف {len(to_delete)} سطراً مكرَّراً من {len(affected_safe_boxes)} خزينة. أُبقي على {len(to_keep)} سطر تصحيح حقيقي.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    run(apply=args.apply)
