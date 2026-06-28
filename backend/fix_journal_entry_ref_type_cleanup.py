"""
fix_journal_entry_ref_type_cleanup.py
=======================================
يعيد بناء ما فعله fix_voucher_safebox_transactions_and_posting.py وسكريبت
التصحيح اللاحق (fix_duplicate_safebox_transactions_from_backfill.py) بطريقة
أسلم تماماً، بعد اكتشاف أن نظام SafeBoxTransaction في هذا المشروع يحوي
**14 نوع مرجع مختلفاً تاريخياً** (voucher, office_reservation, invoice_*,
hist_gold_recon_invoice_reversal, voucher_reversal, je_correction,
opening_balance, ledger_balance_adjustment...) -- محاولة سكريبت التصحيح
السابق تعداد نوعين فقط (voucher, office_reservation) كانت غير كافية: فاتها
نوع je_correction تحديداً، فبقي تكرار حقيقي في حالة "مكتب الديوان" (قيد
WGT-2026-00012 له صفّان: واحد قديم بنوع je_correction، وآخر جديد بنوع
journal_entry من سكريبتي).

بدل محاولة تعداد كل نوع تاريخي يدوياً (خطر تكرار الغلطة بفوات نوع آخر)، هذا
السكريبت يعتمد على حقيقة واحدة مؤكَّدة 100%: **نوع المرجع 'journal_entry' لا
ينشئه أي مسار في النظام إلا استدعاء _rebuild_safe_box_transactions_for_journal_entry
لقيد سنده/حجزه reference_type في ('voucher', 'office_reservation')** -- وهذا
لم يحدث قط إلا من سكريبتي الأخير. فكل صف بهذا النوع بالضبط هو من فعلي، بلا
استثناء، بلا حاجة لمطابقة شيء لإثبات ذلك.

الخطوات:

  المرحلة أ -- حذف كامل: كل صف SafeBoxTransaction بنوع مرجع 'journal_entry'
  يُحذف، بلا أي محاولة مطابقة (مؤكَّد أنه إضافة سكريبتي، صحيحاً كان أم مكرراً).

  المرحلة ب -- فحص شامل لحجوزات المكاتب فقط (السندات لا تحتاج أي إعادة بناء،
  أكَّدنا أن _append_safe_transactions_for_voucher تغطّيها دائماً): لكل قيد
  reference_type='office_reservation' يمسّ حساب خزينة، يُفحص: هل توجد أي
  حركة أخرى (أي نوع مرجع كان) تمثّل هذا القيد بالفعل؟ عبر:
    1. صف ref_type='office_reservation' بنفس ref_id (معرّف الحجز).
    2. أي صف notes فيه "je_id=<معرف هذا القيد>".
    3. أي صف notes فيه رقم القيد نفسه (مثل "WGT-2026-00023") كنص فرعي --
       يغطّي أسلوب je_correction وأي أسلوب تسمية مشابه مستقبلاً.
  لو لم توجد أي تغطية بأي من الطرق الثلاث: القيد ناقص فعلاً، يُعاد إنشاء
  حركته. لو وُجدت تغطية بأي طريقة: لا يُعاد إنشاء شيء (مغطّى أصلاً).

الوضع الافتراضي: DRY RUN (لا يكتب شيئاً). --apply للتنفيذ.

تشغيل:
    docker cp backend/fix_journal_entry_ref_type_cleanup.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/fix_journal_entry_ref_type_cleanup.py            # dry run
    docker exec yasargold-backend python backend/fix_journal_entry_ref_type_cleanup.py --apply    # تنفيذ فعلي
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, JournalEntry, SafeBox, SafeBoxTransaction


def run(apply: bool) -> None:
    with app.app_context():
        # ── المرحلة أ: حذف كل صف ref_type='journal_entry' (مؤكَّد أنه من سكريبتي) ──
        je_rows = SafeBoxTransaction.query.filter_by(ref_type='journal_entry').all()
        print(f"المرحلة أ -- سطور ref_type='journal_entry' (كلها من سكريبتي): {len(je_rows)}")
        je_safe_boxes = sorted({tx.safe_box_id for tx in je_rows})
        safe_names_a = {sb.id: sb.name for sb in SafeBox.query.filter(SafeBox.id.in_(je_safe_boxes)).all()}
        for sb_id in je_safe_boxes:
            count = sum(1 for tx in je_rows if tx.safe_box_id == sb_id)
            print(f"  - خزينة #{sb_id} ({safe_names_a.get(sb_id, '?')}): {count} سطراً سيُحذف بالكامل")

        # ── المرحلة ب: فحص شامل لحجوزات المكاتب ──
        safe_box_account_ids = {
            int(sb.account_id) for sb in SafeBox.query.all() if sb.account_id is not None
        }

        office_res_entries = (
            JournalEntry.query
            .filter(JournalEntry.reference_type == 'office_reservation')
            .filter(JournalEntry.is_deleted.is_(False))
            .filter(JournalEntry.is_posted.is_(True))
            .all()
        )

        # كل الصفوف غير journal_entry (المرجع التاريخي المتنوع) -- نستخدمها كلها للفحص
        other_rows = SafeBoxTransaction.query.filter(SafeBoxTransaction.ref_type != 'journal_entry').all()

        direct_match = {
            (r.ref_id) for r in other_rows
            if (r.ref_type or '').strip().lower() == 'office_reservation' and r.ref_id is not None
        }
        notes_blob = [(r.notes or '') for r in other_rows]

        genuinely_missing = []
        already_covered_count = 0

        for entry in office_res_entries:
            lines = [l for l in entry.lines if not getattr(l, 'is_deleted', False)]
            touches_safe = any(
                int(l.account_id) in safe_box_account_ids
                for l in lines if l.account_id is not None
            )
            if not touches_safe:
                continue

            reservation_id = entry.reference_id
            covered = reservation_id in direct_match

            if not covered:
                je_id_marker = f"je_id={entry.id}"
                covered = any(je_id_marker in n for n in notes_blob)

            if not covered and entry.entry_number:
                covered = any(entry.entry_number in n for n in notes_blob)

            if covered:
                already_covered_count += 1
            else:
                genuinely_missing.append((entry, lines))

        print(f"\nالمرحلة ب -- قيود حجوزات مكاتب تمسّ خزينة:")
        print(f"  مغطّاة بالفعل بطريقة أو بأخرى (لن تُلمَس): {already_covered_count}")
        print(f"  ناقصة فعلاً (ستُعاد إضافتها): {len(genuinely_missing)}")
        for entry, _lines in genuinely_missing[:30]:
            print(f"    - JE#{entry.id} ({entry.entry_number})")
        if len(genuinely_missing) > 30:
            print(f"    ... و{len(genuinely_missing) - 30} غيرها")

        if not apply:
            print("\n(DRY RUN) لتطبيق التغيير فعليًا أضف --apply")
            return

        from routes import _rebuild_safe_box_transactions_for_journal_entry

        for tx in je_rows:
            db.session.delete(tx)
        db.session.flush()

        for entry, lines in genuinely_missing:
            _rebuild_safe_box_transactions_for_journal_entry(entry, lines, created_by='system')

        db.session.commit()
        print(f"\nتم: حُذف {len(je_rows)} سطراً، أُعيد إنشاء حركة لـ{len(genuinely_missing)} حجز مكتب ناقص فعلاً.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    run(apply=args.apply)
