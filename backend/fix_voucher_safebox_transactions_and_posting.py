"""
fix_voucher_safebox_transactions_and_posting.py
=================================================
تصحيح: نسخة سابقة من هذا السكريبت (شُغِّلت على الإنتاج، انظر
fix_duplicate_safebox_transactions_from_backfill.py للتفاصيل الكاملة وكيفية
تصحيح أثرها) كانت تتعامل أيضاً مع reference_type='voucher'، بافتراض أن
السندات لا تُولِّد حركة SafeBoxTransaction إطلاقاً. كان هذا خاطئاً: كل سند
مغطّى بالفعل بدالة منفصلة موجودة سلفاً (_append_safe_transactions_for_voucher
-- تُستدعى من كل مسارات إنشاء/اعتماد السندات، وفيها حارس idempotency خاص).
معالجة السندات هنا حُذفت لمنع تكرار تلك الغلطة لو أُعيد تشغيل هذا السكريبت.

ما تبقّى صحيحاً ومطلوباً: حجوزات المكاتب (office_reservation). لا توجد لها
دالة مكافئة -- قيد "إرسال ذهب للحجز" (تنفّذه create_office_reservation) كان
يُرحَّل (is_posted=True) دون أن يُولِّد حركة SafeBoxTransaction المقابلة له،
فتبقى بطاقة خزينة المكتب الذهبية غير متطابقة مع كشف حسابه الحقيقي. مُصحَّح
الآن في routes.py لكل حجز جديد؛ هذا السكريبت يُعبّئ البيانات التاريخية فقط.

المنطق: لكل قيد محاسبي reference_type='office_reservation' غير محذوف
ومُرحَّل (is_posted=True -- وهذه دائماً الحال هنا، تُرحَّل عند الإنشاء
مباشرة)، يُعاد بناء سطور SafeBoxTransaction المقابلة له عبر
_rebuild_safe_box_transactions_for_journal_entry -- الدالة نفسها idempotent
(تحذف ref_type='journal_entry' القديم أولاً) فتشغيلها على قيد سليم لا يُغيّر
شيئاً.

الوضع الافتراضي: DRY RUN (لا يكتب شيئاً، فقط يطبع ما سيحدث). --apply للتنفيذ.

تشغيل:
    docker cp backend/fix_voucher_safebox_transactions_and_posting.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/fix_voucher_safebox_transactions_and_posting.py            # dry run
    docker exec yasargold-backend python backend/fix_voucher_safebox_transactions_and_posting.py --apply    # تنفيذ فعلي
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, JournalEntry, SafeBox
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
            .filter(JournalEntry.reference_type == 'office_reservation')
            .filter(JournalEntry.is_deleted.is_(False))
            .filter(JournalEntry.is_posted.is_(True))
            .all()
        )
        candidate_entries = [e for e in candidate_entries if not _is_manual_like_journal_entry(e)]

        print(f"قيود حجوزات مكاتب مرشَّحة (غير محذوفة، مُرحَّلة): {len(candidate_entries)}\n")

        to_rebuild_sbt = []
        for entry in candidate_entries:
            lines = [l for l in entry.lines if not getattr(l, 'is_deleted', False)]
            touches_safe_box = any(
                int(l.account_id) in safe_box_account_ids
                for l in lines if l.account_id is not None
            )
            if touches_safe_box:
                to_rebuild_sbt.append((entry, lines))

        print(f"قيود ستُعاد بناء SafeBoxTransaction لها (تمس حساب خزينة): {len(to_rebuild_sbt)}")
        for entry, _lines in to_rebuild_sbt[:20]:
            print(f"  - JE#{entry.id} ({entry.entry_number})")
        if len(to_rebuild_sbt) > 20:
            print(f"  ... و{len(to_rebuild_sbt) - 20} غيرها")

        if not apply:
            print("\n(DRY RUN) لتطبيق التغيير فعليًا أضف --apply")
            return

        for entry, lines in to_rebuild_sbt:
            _rebuild_safe_box_transactions_for_journal_entry(entry, lines, created_by='system')

        db.session.commit()
        print(f"\nتم: أُعيد بناء SafeBoxTransaction لـ{len(to_rebuild_sbt)} قيد حجز مكتب.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    run(apply=args.apply)
