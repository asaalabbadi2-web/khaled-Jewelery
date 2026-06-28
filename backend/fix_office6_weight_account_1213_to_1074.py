"""
fix_office6_weight_account_1213_to_1074.py
=============================================
يصحّح خللاً محدداً وموثَّقاً بالتفصيل (انظر diagnose_latest_office_reservation.py
وdiagnose_1213_vs_1074_balances.py لمسار الاكتشاف الكامل):

حساب #1072 (الحساب المالي لمكتب "مكاتب تسكير فورية واشخاص") لا يزال
memo_account_id فيه يشير إلى حساب #1213 -- حساب اسمه الصريح "[غير مستخدم --
مكرَّر، استُبدل بحساب 1074]"، أي متروك فعلياً منذ دمج/استبدال سابق لم يُحدَّث
معه هذا المؤشر. نتيجة ذلك: قيد الحجز الأخير (JE#4709 / WGT-2026-00027،
الحجز RES-...-0021، 120 غم عيار 24) سجّل الذهب على #1213 بدل #1074.

تأكَّد عبر دفتر الأستاذ مباشرة (المصدر الرسمي الوحيد):
  - #1213: رصيد 24k = +120.0 (يجب أن يكون 0 -- لا يوجد أي سطر آخر تاريخياً
    على هذا الحساب غير JE#4709، فلا تراكم سابق يُقلق).
  - #1074: رصيد 24k = -120.0 (يُفترض أن يصبح 0 بعد تصحيح هذا القيد).

الإصلاح (بخطوتين، باختيار المستخدم: تعديل مباشر لسطر القيد، لا قيد عكسي --
لأنه خطأ اختيار حساب حديث (يوم واحد) لم يُبنَ عليه أي شيء آخر):

  1. ربط Account(1072) بـAccount(1074) عبر account_pair_service.link_accounts
     (لا تعيين مباشر لـmemo_account_id -- هذا أول استخدام فعلي للخدمة
     المركزية الجديدة؛ انظر audit_account_memo_invariants.py الذي كشف أن
     الكتابة المباشرة من 36 موضعاً مختلفاً هي السبب الجذري لهذه الفئة من
     الأخطاء). الخدمة تفسخ تلقائياً أي ربط سابق على أي من الطرفين، شاملاً
     أي حساب ثالث آخر قد يشير خطأً لـ1074 (duplicate_target لم نتحقق منه
     يدوياً لـ1074 تحديداً -- الخدمة تضمنه تلقائياً).
  2. تعديل JournalEntryLine الوحيد على JE#4709 الذي account_id=1213 ليصبح
     account_id=1074 مباشرة (لا حذف/إعادة إنشاء -- نفس السطر، حقل واحد فقط).

الوضع الافتراضي: DRY RUN (يطبع ما سيحدث بلا كتابة). --apply للتنفيذ الفعلي.

تشغيل:
    docker cp backend/fix_office6_weight_account_1213_to_1074.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/fix_office6_weight_account_1213_to_1074.py            # dry run
    docker exec yasargold-backend python backend/fix_office6_weight_account_1213_to_1074.py --apply    # تنفيذ فعلي
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, Account, JournalEntry, JournalEntryLine
from services.live_balances import live_balances_by_account_ids
from account_pair_service import link_accounts, AccountPairLinkError

OLD_ACCOUNT_ID = 1213
NEW_ACCOUNT_ID = 1074
OFFICE_FINANCIAL_ACCOUNT_ID = 1072
TARGET_JE_ID = 4709


def run(apply: bool) -> None:
    with app.app_context():
        office_account = Account.query.get(OFFICE_FINANCIAL_ACCOUNT_ID)
        if not office_account:
            print(f"❌ الحساب #{OFFICE_FINANCIAL_ACCOUNT_ID} غير موجود -- إيقاف.")
            return

        print(f"الحساب المالي #{office_account.id} {office_account.name}")
        print(f"  memo_account_id الحالي: {office_account.memo_account_id}")
        will_update_memo = office_account.memo_account_id != NEW_ACCOUNT_ID
        if will_update_memo:
            print(f"  -> سيُحدَّث إلى: {NEW_ACCOUNT_ID}")
        else:
            print(f"  -> مضبوط بالفعل على {NEW_ACCOUNT_ID}، لن يُلمَس.")

        entry = JournalEntry.query.get(TARGET_JE_ID)
        if not entry:
            print(f"❌ القيد #{TARGET_JE_ID} غير موجود -- إيقاف.")
            return

        target_lines = [
            l for l in entry.lines
            if not getattr(l, 'is_deleted', False) and l.account_id == OLD_ACCOUNT_ID
        ]
        print(f"\nالقيد {entry.entry_number} (id={entry.id}):")
        if not target_lines:
            print(f"  لا يوجد أي سطر بحساب #{OLD_ACCOUNT_ID} -- ربما صُحِّح بالفعل. لن يُلمَس القيد.")
        for line in target_lines:
            print(
                f"  سطر #{line.id}: حساب={line.account_id} -> سيصبح {NEW_ACCOUNT_ID} | "
                f"مدين_24k={line.debit_24k or 0} دائن_24k={line.credit_24k or 0}"
            )

        before = live_balances_by_account_ids([OLD_ACCOUNT_ID, NEW_ACCOUNT_ID])
        print(f"\nالأرصدة قبل التصحيح: #{OLD_ACCOUNT_ID}={before.get(OLD_ACCOUNT_ID)} | "
              f"#{NEW_ACCOUNT_ID}={before.get(NEW_ACCOUNT_ID)}")

        if not apply:
            print("\n(DRY RUN) لتطبيق التغيير فعليًا أضف --apply")
            return

        if will_update_memo:
            new_memo_account = Account.query.get(NEW_ACCOUNT_ID)
            if not new_memo_account:
                print(f"❌ الحساب #{NEW_ACCOUNT_ID} غير موجود -- إيقاف.")
                return
            try:
                link_accounts(office_account, new_memo_account, created_by='fix_office6_weight_account_1213_to_1074')
            except AccountPairLinkError as exc:
                print(f"❌ رفضت خدمة الربط العملية: {exc}")
                return

        for line in target_lines:
            line.account_id = NEW_ACCOUNT_ID
            db.session.add(line)

        db.session.commit()

        after = live_balances_by_account_ids([OLD_ACCOUNT_ID, NEW_ACCOUNT_ID])
        print(f"\nتم. الأرصدة بعد التصحيح: #{OLD_ACCOUNT_ID}={after.get(OLD_ACCOUNT_ID)} | "
              f"#{NEW_ACCOUNT_ID}={after.get(NEW_ACCOUNT_ID)}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    run(apply=args.apply)
