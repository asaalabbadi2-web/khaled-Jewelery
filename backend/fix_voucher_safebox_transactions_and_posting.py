"""
fix_voucher_safebox_transactions_and_posting.py
=================================================
يصلح ثغرة اكتُشفت عبر فحص خزينتين مختلفتين تماماً (خزينة ذهب موظف يوسف
الشعبي، حساب 949 -- وخزينة مكتب "مكاتب تسكير فورية وأشخاص"، حساب 1074):
في كلتا الحالتين الرصيد الحقيقي (كشف الحساب) كان مختلفاً عن رصيد بطاقة
الخزينة وأداة "التحويل بين الخزائن" (تعتمد كلتاهما على SafeBoxTransaction
لا على القيود المحاسبية مباشرة)، لأن بعض القيود المحاسبية الصحيحة لم تُولِّد
حركة SafeBoxTransaction المقابلة لها مطلقاً. النتيجتان مختلفتا الاتجاه لكن
السبب نفسه بالضبط:
  - يوسف الشعبي: سندات "تحويل خزنة ذهب" (صادرة) لم تُسجَّل خروجاً، فظهر
    المتاح أعلى من الحقيقي وتكرر تحويل "فائض" وهمي لشهور (~59.6 جم كل مرة).
  - مكتب التسكير: قيد "إرسال ذهب للحجز" (وارد) لم يُسجَّل دخولاً، فظهرت
    بطاقة الخزينة بالسالب (-175 جم) بينما كشف الحساب الحقيقي = صفر.

السببان الجذريان (مُصحَّحان بالفعل في routes.py، هذا السكريبت للبيانات
التاريخية فقط):

  1. create_journal_entry_from_voucher() (كل السندات: تحويل، صرف، قبض،
     تسوية) و create_office_reservation() (قيد "إرسال ذهب للحجز" تحديداً)
     لم يكونا يستدعيان _rebuild_safe_box_transactions_for_journal_entry()
     إطلاقاً. الدالة موجودة وتعمل بشكل صحيح (تُستدعى من شاشة القيد اليدوي)
     لكنها لم تكن مربوطة بمساري السندات وحجوزات المكاتب.

  2. فحص "الترحيل التلقائي" (auto-post) داخل create_journal_entry_from_voucher
     كان يقرأ الإعدادات عبر Settings.query.first() مباشرة بلا ترتيب -- غير
     آمن إن وُجد أكثر من سجل إعدادات (الحالة الموجودة فعلياً، انظر
     _get_settings_singleton وتعليقها الصريح). فبعض القيود انتهت بـ
     is_posted=None رغم أن إعدادات الترحيل التلقائي الحالية تقول "مفعّل" --
     وهذا بدوره يمنع _rebuild_safe_box_transactions_for_journal_entry من فعل
     أي شيء لها أصلاً (تتطلب is_posted=True). لا يؤثر على قيود حجوزات
     المكاتب: تلك تُرحَّل مباشرة عند الإنشاء (is_posted=True) بلا فحص إعدادات.

ما يفعله هذا السكريبت (بيانات تاريخية فقط -- الجديد يُصحَّح تلقائياً الآن):

  المرحلة أ: لكل قيد reference_type='voucher' غير محذوف، إن كان سنده
  معتمَداً (Voucher.status == 'approved') ولم يكن القيد is_posted بعد --
  يُرحَّل (is_posted=True, is_draft=False, posted_at, posted_by).

  المرحلة ب: لكل قيد reference_type في ('voucher', 'office_reservation')
  مُرحَّل (بعد المرحلة أ أو كان مُرحَّلاً أصلاً)، يُعاد بناء سطور
  SafeBoxTransaction المقابلة له عبر _rebuild_safe_box_transactions_for_journal_entry
  -- الدالة نفسها idempotent (تحذف القديم أولاً) فتشغيلها على قيد سليم لا
  يُغيّر شيئاً.

لا يلمس القيود يدوية المصدر الحقيقية (reference_type في '', 'manual',
'journal_entry') -- مستثناة بتصميم النظام نفسه (_is_manual_like_journal_entry)،
ولا قيود الفواتير (لها مسارها الخاص عبر /safe-boxes/repair-transactions).

الوضع الافتراضي: DRY RUN (لا يكتب شيئاً، فقط يطبع ما سيحدث). --apply للتنفيذ.

تشغيل:
    docker cp backend/fix_voucher_safebox_transactions_and_posting.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/fix_voucher_safebox_transactions_and_posting.py            # dry run
    docker exec yasargold-backend python backend/fix_voucher_safebox_transactions_and_posting.py --apply    # تنفيذ فعلي
"""

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, JournalEntry, Voucher, SafeBox
from routes import (
    _is_manual_like_journal_entry,
    _rebuild_safe_box_transactions_for_journal_entry,
)


def run(apply: bool) -> None:
    with app.app_context():
        safe_box_account_ids = {
            int(sb.account_id) for sb in SafeBox.query.all() if sb.account_id is not None
        }

        candidate_entries = (
            JournalEntry.query
            .filter(JournalEntry.reference_type.in_(['voucher', 'office_reservation']))
            .filter(JournalEntry.is_deleted.is_(False))
            .all()
        )
        candidate_entries = [e for e in candidate_entries if not _is_manual_like_journal_entry(e)]

        by_type = {}
        for e in candidate_entries:
            by_type[e.reference_type] = by_type.get(e.reference_type, 0) + 1
        print(f"قيود مرشَّحة (غير محذوفة): {len(candidate_entries)}  {by_type}\n")

        to_post = []
        to_rebuild_sbt = []
        skipped_not_approved = 0

        for entry in candidate_entries:
            voucher = None
            label = entry.reference_type
            if entry.reference_type == 'voucher':
                voucher = Voucher.query.get(entry.reference_id) if entry.reference_id else None
                approved = bool(voucher) and (voucher.status == 'approved')
                label = voucher.voucher_number if voucher else '?'
            else:
                # office_reservation entries are posted at creation time
                # directly, with no separate approval gate to check.
                approved = True

            needs_posting = entry.is_posted is not True
            if needs_posting:
                if approved:
                    to_post.append((entry, voucher, label))
                else:
                    skipped_not_approved += 1
                    continue  # don't touch SBTs for entries whose voucher isn't even approved

            lines = [l for l in entry.lines if not getattr(l, 'is_deleted', False)]
            touches_safe_box = any(
                int(l.account_id) in safe_box_account_ids
                for l in lines if l.account_id is not None
            )
            if touches_safe_box:
                to_rebuild_sbt.append((entry, voucher, label, lines))

        print(f"قيود ستُرحَّل (is_posted: None/False -> True، معتمَدة): {len(to_post)}")
        for entry, _voucher, label in to_post[:20]:
            print(f"  - JE#{entry.id} ({entry.entry_number})  [{entry.reference_type}] {label}")
        if len(to_post) > 20:
            print(f"  ... و{len(to_post) - 20} غيرها")

        print(f"\nقيود ستُعاد بناء SafeBoxTransaction لها (تمس حساب خزينة): {len(to_rebuild_sbt)}")
        for entry, _voucher, label, _lines in to_rebuild_sbt[:20]:
            print(f"  - JE#{entry.id} ({entry.entry_number})  [{entry.reference_type}] {label}")
        if len(to_rebuild_sbt) > 20:
            print(f"  ... و{len(to_rebuild_sbt) - 20} غيرها")

        print(f"\nقيود سندها غير معتمَد (لم تُلمَس إطلاقاً): {skipped_not_approved}")

        if not apply:
            print("\n(DRY RUN) لتطبيق التغيير فعليًا أضف --apply")
            return

        now = datetime.now()
        for entry, voucher, _label in to_post:
            entry.is_posted = True
            entry.is_draft = False
            if not entry.posted_at:
                entry.posted_at = now
            if not entry.posted_by:
                entry.posted_by = (voucher.created_by if voucher else None) or 'system'

        db.session.flush()

        for entry, voucher, _label, lines in to_rebuild_sbt:
            _rebuild_safe_box_transactions_for_journal_entry(
                entry, lines, created_by=((voucher.created_by if voucher else None) or 'system')
            )

        db.session.commit()
        print(f"\nتم: رُحِّل {len(to_post)} قيداً، وأُعيد بناء SafeBoxTransaction لـ{len(to_rebuild_sbt)} قيداً.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    run(apply=args.apply)
