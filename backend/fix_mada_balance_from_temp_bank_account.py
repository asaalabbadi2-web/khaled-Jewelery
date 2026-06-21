"""
fix_mada_balance_from_temp_bank_account.py
=============================================
تصحيح بيانات حقيقي بطلب صريح من المستخدم (لا تشخيصي): نقل 3700.00 ريال من
"حساب بنكي مؤقت" (account_id=1154، خزينة بنك الرياض مؤقتة) إلى حساب مدى
للمقاصة (account_id=777)، لتغطية المستحق الحالي بالضبط (انظر
/clearing/settlements/pending-transactions?clearing_safe_box_id=32).

السياق الكامل: JE-2026-02141 (2026-05-14، "تسوية فارق رصيد تاريخي - مدى")
نقل 4380.00 من مدى إلى هذا الحساب المؤقت لتصحيح فارق خارجي (مع كشف بنك
الرياض الحقيقي على الأرجح) لا أثر له داخل بيانات النظام. المستخدم قرّر
إعادة 3700.00 من ذلك المبلغ إلى مدى تحديداً، ويبقي 680.00 في الحساب
المؤقت (مرتبطة بمعالجة سابقة منفصلة).

يُنشئ سند تعديل (adjustment) حقيقي، مرئياً في شاشة السندات برقم تسلسلي،
بسطرين متوازنين:
  - مدين: مدى (777) +3700.00   (يرفع رصيدها)
  - دائن: حساب بنكي مؤقت (1154) +3700.00   (يخفّض رصيده)
ثم يُنشئ القيد المحاسبي المرتبط عبر create_journal_entry_from_voucher —
نفس الآلية المستخدَمة في كل سندات النظام — فيحصل تلقائياً على
reference_type='voucher' (مسموح فعلاً في حارس حسابات المقاصة الجديد)،
بخلاف JE-2026-02141 الذي لم يكن مرتبطاً بأي سند ولا reference_type أصلاً.

ضمان أمان: يتحقّق من الرصيد الفعلي الحالي لكلا الحسابين عبر
live_balances_by_account_ids (نفس الدالة التي يعتمد عليها كل النظام) قبل
أي تنفيذ، ويرفض لو كان رصيد الحساب المؤقت أقل من 3700.00.

الوضع الافتراضي: DRY RUN. --apply للتنفيذ الفعلي.

تشغيل:
    docker cp backend/fix_mada_balance_from_temp_bank_account.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/fix_mada_balance_from_temp_bank_account.py            # dry run
    docker exec yasargold-backend python backend/fix_mada_balance_from_temp_bank_account.py --apply     # تنفيذ فعلي
"""

import os
import sys
import json
import argparse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, Voucher, VoucherAccountLine, Account
from services.live_balances import live_balances_by_account_ids

MADA_ACCOUNT_ID = 777
TEMP_BANK_ACCOUNT_ID = 1154
AMOUNT = 3700.00


def run(apply: bool):
    with app.app_context():
        from routes import generate_voucher_number, create_journal_entry_from_voucher

        run_dt = datetime.now(timezone.utc)

        mada_account = Account.query.get(MADA_ACCOUNT_ID)
        temp_account = Account.query.get(TEMP_BANK_ACCOUNT_ID)
        if not mada_account or not temp_account:
            print("❌ توقّف: أحد الحسابين غير موجود.")
            return

        balances_before = live_balances_by_account_ids([MADA_ACCOUNT_ID, TEMP_BANK_ACCOUNT_ID])
        mada_before = balances_before.get(MADA_ACCOUNT_ID, {}).get('cash', 0.0)
        temp_before = balances_before.get(TEMP_BANK_ACCOUNT_ID, {}).get('cash', 0.0)

        print(f"{'تطبيق فعلي' if apply else 'DRY RUN — لن يُحفظ شيء في قاعدة البيانات'}")
        print(f"تاريخ التنفيذ: {run_dt.isoformat()}\n")
        print(f"Before:")
        print(f"  مدى (#{MADA_ACCOUNT_ID}) رصيد فعلي = {mada_before:.2f}")
        print(f"  حساب بنكي مؤقت (#{TEMP_BANK_ACCOUNT_ID}) رصيد فعلي = {temp_before:.2f}\n")

        if temp_before < AMOUNT - 0.01:
            print(f"❌ توقّف: رصيد الحساب المؤقت ({temp_before:.2f}) أقل من المبلغ المطلوب نقله ({AMOUNT:.2f}).")
            return

        mada_after_expected = round(mada_before + AMOUNT, 2)
        temp_after_expected = round(temp_before - AMOUNT, 2)
        print(f"After (متوقَّع):")
        print(f"  مدى (#{MADA_ACCOUNT_ID}) رصيد فعلي = {mada_after_expected:.2f}")
        print(f"  حساب بنكي مؤقت (#{TEMP_BANK_ACCOUNT_ID}) رصيد فعلي = {temp_after_expected:.2f}\n")

        if not apply:
            print("(DRY RUN) لتطبيق التغيير فعليًا أضف --apply")
            db.session.rollback()
            return

        voucher_number = generate_voucher_number('adjustment', voucher_date=run_dt)
        voucher = Voucher(
            voucher_number=voucher_number,
            voucher_type='adjustment',
            date=run_dt,
            description=(
                f'تصحيح رصيد مدى: استرجاع {AMOUNT:.2f} من الحساب البنكي المؤقت '
                f'(جزء من JE-2026-02141 "تسوية فارق رصيد تاريخي" بتاريخ 2026-05-14) '
                f'لتغطية مستحقات تحصيل حالية بنفس القيمة'
            ),
            notes=(
                'يُبقي 680.00 من أصل 4380.00 في الحساب المؤقت (مرتبطة بمعالجة سابقة '
                'منفصلة يتذكّرها المستخدم). راجع المحادثة/التحقيق المرتبط بتاريخ '
                f'{run_dt.date().isoformat()} لتفاصيل كاملة.'
            ),
            created_by='admin',
            status='approved',
            approved_by='admin',
            approved_at=run_dt,
            amount_cash=AMOUNT,
            amount_gold=0.0,
        )
        db.session.add(voucher)
        db.session.flush()

        db.session.add(VoucherAccountLine(
            voucher_id=voucher.id,
            account_id=MADA_ACCOUNT_ID,
            line_type='debit',
            amount_type='cash',
            amount=AMOUNT,
            description='استرجاع جزء من فارق رصيد تاريخي (JE-2026-02141) لتغطية مستحقات حالية',
        ))
        db.session.add(VoucherAccountLine(
            voucher_id=voucher.id,
            account_id=TEMP_BANK_ACCOUNT_ID,
            line_type='credit',
            amount_type='cash',
            amount=AMOUNT,
            description='تحويل لحساب مدى — تصحيح فارق رصيد تاريخي (جزئي)',
        ))
        db.session.flush()

        journal_entry = create_journal_entry_from_voucher(voucher)
        if journal_entry:
            voucher.journal_entry_id = journal_entry.id

        mada_account.update_balance(cash_amount=AMOUNT)
        temp_account.update_balance(cash_amount=-AMOUNT)

        report = {
            'run_at': run_dt.isoformat(),
            'applied': True,
            'voucher_id': voucher.id,
            'voucher_number': voucher.voucher_number,
            'journal_entry_id': voucher.journal_entry_id,
            'before': {'mada': mada_before, 'temp_bank_account': temp_before},
            'after_expected': {'mada': mada_after_expected, 'temp_bank_account': temp_after_expected},
        }
        reports_dir = os.path.join(os.path.dirname(__file__), 'reports')
        os.makedirs(reports_dir, exist_ok=True)
        report_path = os.path.join(
            reports_dir,
            f"fix_mada_balance_from_temp_bank_account_{run_dt.strftime('%Y%m%dT%H%M%SZ')}_applied.json",
        )
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        db.session.commit()

        balances_after = live_balances_by_account_ids([MADA_ACCOUNT_ID, TEMP_BANK_ACCOUNT_ID])
        print(f"✅ تم الحفظ. السند: {voucher.voucher_number} (id={voucher.id}), "
              f"القيد: JE#{voucher.journal_entry_id}")
        print(f"After (فعلي):")
        print(f"  مدى رصيد فعلي = {balances_after.get(MADA_ACCOUNT_ID, {}).get('cash', 0.0):.2f}")
        print(f"  حساب بنكي مؤقت رصيد فعلي = {balances_after.get(TEMP_BANK_ACCOUNT_ID, {}).get('cash', 0.0):.2f}")
        print(f"تم كتابة التقرير: {report_path}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    run(apply=args.apply)
