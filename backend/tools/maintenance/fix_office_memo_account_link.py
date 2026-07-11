"""
fix_office_memo_account_link.py
=============================================
تصحيح بيانات حقيقي بطلب صريح من المستخدم -- تصحيح ربط حساب مفكرة مكتب
"مكاتب تسكير فورية واشخاص" (office_id=6).

السياق الكامل: اكتُشف عبر تحقيق منفصل أن كود إنشاء حجوزات الذهب الخام
كان يحلّ حساب الوزن لكل مكتب عبر مسارين مستقلّين غير متّسقين:
  - النقدي: office.account_category_id (مباشر) -> حساب 1072
  - الوزني (قبل التصحيح البرمجي): supplier.default_safe_box.account_id -> حساب 1074
بينما حساب 1072 نفسه له memo_account_id رسمي مُعرَّف = 1213، لم يُستخدَم
إطلاقاً في مسار إنشاء الحجوزات.

تحقّقنا من كل المكاتب الأربعة في النظام: في 3 منها المساران يتفقان
بالصدفة على نفس الحساب (فالخلل البرمجي كان مُقنَّعاً تماماً). فقط هذا
المكتب فيه انحراف فعلي -- فحساب 1213 (المفكرة الرسمية) ظل فارغاً تماماً
(تأكَّد عبر /api/accounts/1213/statement: closing_balance_gold_details
كله صفر)، بينما كل الحركات الوزنية الحقيقية لكل حجوزات هذا المكتب
تاريخياً سُجِّلت في حساب 1074 بدلاً منه.

تم تصحيح الكود (routes.py) ليستخدم account_category_id -> memo_account_id
دائماً كمسار أساسي. هذا السكريبت يصحّح الربط القائم لهذا المكتب تحديداً
ليطابق الواقع الفعلي (حيث توجد البيانات التاريخية الحقيقية)، بدل تحريك
أي قيد محاسبي تاريخي:

  - Account(1072).memo_account_id: 1213 -> 1074
    (نُعيد توجيه الرابط الرسمي إلى الحساب الذي يحوي البيانات الفعلية،
    بدل نقل سنوات من حركات وزن من 1074 إلى 1213 الفارغ -- تصحيح ربط
    لا تصحيح بيانات مالية، فلا تأثير على أي رصيد أو قيد قائم.)
  - Account(1213).name: إضافة بادئة توضيحية "[غير مستخدم -- مكرَّر]"
    حتى لا يُستخدَم بالخطأ مستقبلاً (لا يوجد حقل is_active على Account
    في هذا النظام، فالتوضيح في الاسم هو الطريقة الآمنة المتاحة بدل حذفه
    -- يبقى موجوداً لأي مرجع تاريخي محتمل لم نكتشفه).

ضمان أمان: يتحقّق أن الحالة الحالية مطابقة تماماً لما هو متوقَّع (1072.
memo_account_id == 1213 فعلاً، 1213 لا يزال بلا أي رصيد وزني) قبل أي
تعديل -- يتوقف بدل التنفيذ لو وجد أن الوضع تغيّر عن آخر تحقيق.

الوضع الافتراضي: DRY RUN. --apply للتنفيذ الفعلي.

تشغيل:
    docker cp backend/fix_office_memo_account_link.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/fix_office_memo_account_link.py            # dry run
    docker exec yasargold-backend python backend/fix_office_memo_account_link.py --apply     # تنفيذ فعلي
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, Account, Office

OFFICE_ID = 6
FINANCIAL_ACCOUNT_ID = 1072       # office.account_category_id
OLD_MEMO_ACCOUNT_ID = 1213         # المفكرة الرسمية غير المستخدَمة فعلياً
NEW_MEMO_ACCOUNT_ID = 1074         # الحساب الذي يحوي كل البيانات الوزنية التاريخية الحقيقية
UNUSED_LABEL = '[غير مستخدم -- مكرَّر، استُبدل بحساب 1074]'


def run(apply: bool):
    with app.app_context():
        office = Office.query.get(OFFICE_ID)
        if office is None or office.account_category_id != FINANCIAL_ACCOUNT_ID:
            print(f"❌ توقّف: المكتب (id={OFFICE_ID}) غير موجود أو account_category_id لا يطابق {FINANCIAL_ACCOUNT_ID}.")
            return

        financial_acc = Account.query.get(FINANCIAL_ACCOUNT_ID)
        old_memo_acc = Account.query.get(OLD_MEMO_ACCOUNT_ID)
        new_memo_acc = Account.query.get(NEW_MEMO_ACCOUNT_ID)
        if not financial_acc or not old_memo_acc or not new_memo_acc:
            print("❌ توقّف: أحد الحسابات الثلاثة غير موجود.")
            return

        if financial_acc.memo_account_id != OLD_MEMO_ACCOUNT_ID:
            print(f"❌ توقّف: financial_acc.memo_account_id الحالي ({financial_acc.memo_account_id}) "
                  f"لا يطابق المتوقَّع ({OLD_MEMO_ACCOUNT_ID}) -- يبدو أن أحداً صحّحه مسبقاً أو تغيّرت البيانات.")
            return

        old_memo_weight_total = (
            float(old_memo_acc.balance_18k or 0.0)
            + float(old_memo_acc.balance_21k or 0.0)
            + float(old_memo_acc.balance_22k or 0.0)
            + float(old_memo_acc.balance_24k or 0.0)
        )
        if abs(old_memo_weight_total) > 0.001:
            print(f"❌ توقّف: حساب {OLD_MEMO_ACCOUNT_ID} له رصيد وزني فعلي ({old_memo_weight_total:.3f} جم) -- "
                  f"ليس فارغاً كما تأكَّد في التحقيق. لا تنفيذ تلقائي، يحتاج مراجعة يدوية.")
            return

        print(f"{'تطبيق فعلي' if apply else 'DRY RUN — لن يُحفظ شيء في قاعدة البيانات'}\n")
        print(f"المكتب: {office.name} (id={OFFICE_ID})")
        print(f"الحساب المالي: {financial_acc.name} (#{FINANCIAL_ACCOUNT_ID})")
        print(f"  memo_account_id الحالي: {OLD_MEMO_ACCOUNT_ID} ({old_memo_acc.name}) -- رصيد وزني = {old_memo_weight_total:.3f} (فارغ، مؤكَّد)")
        print(f"  سيصبح: {NEW_MEMO_ACCOUNT_ID} ({new_memo_acc.name}) -- يحوي البيانات الوزنية الفعلية")
        print(f"\nسيُعاد تسمية حساب {OLD_MEMO_ACCOUNT_ID} إلى: \"{old_memo_acc.name} {UNUSED_LABEL}\"")

        if not apply:
            print("\n(DRY RUN) لتطبيق التغيير فعليًا أضف --apply")
            db.session.rollback()
            return

        financial_acc.memo_account_id = NEW_MEMO_ACCOUNT_ID
        if UNUSED_LABEL not in (old_memo_acc.name or ''):
            old_memo_acc.name = f'{old_memo_acc.name} {UNUSED_LABEL}'

        db.session.commit()

        print(f"\n✅ تم التحديث:")
        print(f"   Account({FINANCIAL_ACCOUNT_ID}).memo_account_id = {financial_acc.memo_account_id}")
        print(f"   Account({OLD_MEMO_ACCOUNT_ID}).name = \"{old_memo_acc.name}\"")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    run(apply=args.apply)
