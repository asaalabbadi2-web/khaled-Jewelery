"""
diagnose_latest_office_reservation.py
=======================================
تشخيص فقط -- لا يكتب أي شيء. سبب هذا السكريبت: المستخدم أفاد بأن آخر "حجز
ذهب خام" (OfficeReservation) سجّل الذهب على حساب "مكاتب تسكير فورية
وأشخاص" بشكل غير صحيح.

تعليق موجود في create_office_reservation() (routes.py، بتاريخ 2026-06-23)
يصف هذا الخلل بالضبط سبق إصلاحه: الجانب الوزني كان يحل الحساب عبر
supplier.default_safe_box.account_id (مسار مستقل تماماً عن الجانب النقدي
الذي يستخدم office.account_category_id مباشرة)، فينتج حسابين مختلفين
لنفس المكتب. الإصلاح المفترض: استخدام account_category_id -> memo_account_id
(نفس السلسلة المعتمدة في 32 موضعاً آخر بالنظام)، مع الإبقاء على المسار
القديم (supplier.default_safe_box) كـfallback فقط إن لم يكن memo_account_id
مضبوطاً.

هذا السكريبت يفحص: لكل مكتب اسمه يحوي "تسكير فورية" (أو office_id محدد عبر
--office-id)، آخر حجز له، وأي حساب فعلياً استُخدم في القيد الوزني (_wgt_entry)
المرتبط به -- ويقارنه بما كان "يجب" أن يُستخدم (memo_account_id) وبالمسار
الاحتياطي القديم (default_safe_box.account_id)، ليُحدَّد بدقة:
  1. هل وقع هذا الحجز قبل إصلاح 2026-06-23 أو بعده؟
  2. إن كان بعده ولا يزال خاطئاً: هل office.account_category_id.memo_account_id
     غير مضبوط؟ (وهذا تحديداً ما يُسقطه على المسار الاحتياطي الخاطئ)

تشغيل (قراءة فقط، لا --apply لأنه لا يكتب شيئاً):
    docker cp backend/diagnose_latest_office_reservation.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/diagnose_latest_office_reservation.py
    docker exec yasargold-backend python backend/diagnose_latest_office_reservation.py --office-id 5
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import Office, OfficeReservation, JournalEntry, JournalEntryLine, Account, Supplier, SafeBox


def _account_label(account_id):
    if not account_id:
        return '(غير محدد)'
    acc = Account.query.get(int(account_id))
    if not acc:
        return f'#{account_id} (غير موجود!)'
    return f'#{acc.id} {acc.name} (رقم {acc.account_number})'


def inspect_office(office: Office) -> None:
    print(f"\n{'='*70}")
    print(f"المكتب: #{office.id} {office.name}")

    acc_category_id = office.account_category_id
    print(f"  account_category_id (الحساب المالي): {_account_label(acc_category_id)}")

    memo_account_id = None
    if acc_category_id:
        acc = Account.query.get(int(acc_category_id))
        memo_account_id = getattr(acc, 'memo_account_id', None) if acc else None
    print(f"  memo_account_id (الحساب الوزني الصحيح المتوقَّع): {_account_label(memo_account_id)}")
    if not memo_account_id:
        print("  ⚠️  هذا المكتب لا يملك memo_account_id مضبوطاً -- أي قيد وزني جديد له سيسقط على المسار الاحتياطي القديم!")

    supplier = getattr(office, 'supplier', None)
    fallback_account_id = None
    if supplier is not None:
        print(f"  المورد المرتبط: #{supplier.id} {supplier.name}")
        gold_safe = getattr(supplier, 'default_safe_box', None)
        if gold_safe and getattr(gold_safe, 'safe_type', None) == 'gold':
            fallback_account_id = getattr(gold_safe, 'account_id', None)
            print(f"  supplier.default_safe_box: #{gold_safe.id} {gold_safe.name}")
    print(f"  المسار الاحتياطي القديم (supplier.default_safe_box.account_id): {_account_label(fallback_account_id)}")

    latest = (
        OfficeReservation.query
        .filter_by(office_id=office.id)
        .order_by(OfficeReservation.created_at.desc())
        .first()
    )
    if not latest:
        print("  لا توجد حجوزات لهذا المكتب.")
        return

    print(f"\n  آخر حجز: {latest.reservation_code} | تاريخ: {latest.reservation_date} | "
          f"وزن: {latest.weight_grams} عيار {latest.karat} | أُنشئ في: {latest.created_at}")

    wgt_entry = (
        JournalEntry.query
        .filter_by(reference_type='office_reservation', reference_id=latest.id)
        .filter(JournalEntry.description.like('إرسال ذهب للحجز%'))
        .order_by(JournalEntry.id.desc())
        .first()
    )
    if not wgt_entry:
        print("  ⚠️  لا يوجد قيد وزني (WGT) مرتبط بهذا الحجز إطلاقاً -- لم يُسجَّل أي ذهب محاسبياً له!")
        return

    print(f"  القيد الوزني المرتبط: {wgt_entry.entry_number} (id={wgt_entry.id}) | "
          f"مُرحَّل: {wgt_entry.is_posted} | تاريخ: {wgt_entry.date}")

    lines = [l for l in wgt_entry.lines if not getattr(l, 'is_deleted', False)]
    actual_debit_account_id = None
    for line in lines:
        k = latest.karat
        debit_val = getattr(line, f'debit_{k}k', None) or 0.0
        credit_val = getattr(line, f'credit_{k}k', None) or 0.0
        print(f"    سطر: حساب={_account_label(line.account_id)} | مدين_{k}k={debit_val} | دائن_{k}k={credit_val}")
        if debit_val and debit_val > 0:
            actual_debit_account_id = line.account_id

    print()
    if actual_debit_account_id == memo_account_id and memo_account_id:
        print("  ✅ الحساب المستخدم فعلياً = memo_account_id الصحيح. لا خلل في هذا الحجز.")
    elif actual_debit_account_id == fallback_account_id and fallback_account_id:
        print("  ❌ الحساب المستخدم فعلياً = المسار الاحتياطي القديم (الخاطئ)، لا memo_account_id الصحيح.")
        print("     هذا يعني الإصلاح المؤرَّخ 2026-06-23 لم يُطبَّق فعلياً على هذا الحجز (سابق له، أو memo_account_id غير مضبوط).")
    else:
        print(f"  ❓ الحساب المستخدم فعلياً ({_account_label(actual_debit_account_id)}) لا يطابق لا memo_account_id "
              f"ولا المسار الاحتياطي المعروفين -- يحتاج فحصاً يدوياً إضافياً.")


def run(office_id: int | None) -> None:
    with app.app_context():
        if office_id:
            offices = Office.query.filter_by(id=office_id).all()
        else:
            offices = Office.query.filter(Office.name.like('%تسكير فورية%')).all()
            if not offices:
                offices = Office.query.filter(Office.name.like('%تسكير%')).all()

        if not offices:
            print("لم يتم العثور على أي مكتب مطابق. مرر --office-id <رقم> لتحديد المكتب يدوياً.")
            print("\nقائمة كل المكاتب الموجودة:")
            for o in Office.query.order_by(Office.id).all():
                print(f"  #{o.id} {o.name}")
            return

        for office in offices:
            inspect_office(office)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--office-id', type=int, default=None)
    args = parser.parse_args()
    run(office_id=args.office_id)
