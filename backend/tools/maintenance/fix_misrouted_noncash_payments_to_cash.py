"""
fix_misrouted_noncash_payments_to_cash.py
=============================================
تصحيح بيانات حقيقي بطلب صريح من المستخدم -- الخطوة الثانية والأخيرة.

السياق الكامل: دفعة مدى بقيمة 3600.00 (فاتورة SELL-2026-847، السند
الأصلي RV-2026-00976) سُجِّلت خطأً في حساب الصندوق النقدي الرئيسي (755)
بدل حساب مدى للمقاصة (777) -- سببه race condition في
_loadSafeBoxesForPaymentMethod (مُصحَّح في كومِت منفصل، انظر
sales_invoice_screen_v2.dart). InvoicePayment نفسها سجّلت "مدى" بشكل
صحيح دائماً؛ الخطأ كان فقط في حساب القيد.

نفس الفحص الأصلي اكتشف 5 سندات أخرى مشابهة، **استُثنيت كلها بعد مراجعة
المستخدم المباشرة**: RV-2026-00419 وRV-2026-00453 (مُعالجتان بالفعل عبر
قيود تصحيح أقدم، مؤكَّد بمقارنة كشف البنك)، PV-2026-00226 (تصنيف صحيح
أصلاً، اكتشاف خاطئ)، PV-2026-00239/00240 (فاتورة BUY-2026-080 المكرَّرة
حُذفت بالكامل من الإنتاج).

**خطوتان منفصلتان لهذا الواحد المتبقّي (3600):**

الخطوة 1 (تمَّت فعلاً، سند AV-2026-00215، 2026-06-23): نقل 3600 من
الصندوق (755) إلى حساب مدى (777) -- سند تصحيح بسيط بسطرين، شغَّلناه قبل
أن نكتشف الحاجة لتطابق بنية سند تسوية مقاصة حقيقي. **لا يكرّره هذا
السكريبت.**

الخطوة 2 (هذا السكريبت): نقل الـ3600 من حساب مدى (777، حيث تجلس الآن
فعلاً بعد الخطوة 1) إلى حساب البنك (757) -- لأن المستخدم أكّد مباشرة
أن هذه الـ3600 وصلت فعلياً لحساب بنك الرياض في كشف البنك الحقيقي وقتها؛
فهي ليست "مستحقة تحصيل معلَّقة" (وهذا ما يمثّله بقاؤها في 777)، بل مبلغ
وصل البنك فعلاً ولم يُسجَّل عندنا بشكل صحيح فقط. تركها في 777 يُسجِّلها
خطأً كأنها لا تزال بانتظار تحويل للبنك.

لا تعتمد على مراقبة التسوية الآلية (clearing_settlement_scheduler.py)
لتلتقط هذه الحركة تلقائياً: تلك تعتمد على وجود SafeBoxTransaction
بـref_type='invoice_payment' لحساب "المستحق"، ولم تُنشئ الخطوة 1 (ولا
هذا السكريبت) مثل تلك الحركة عمداً -- فهذه تسوية تاريخية يدوية لمبلغ
وصل البنك فعلاً، لا مستحقاً جديداً يجب أن يدخل في حسابات السكدولر
العادية.

**البنية تُطابق سند تسوية المقاصة الطبيعي بالضبط** (نفس الحسابات ونفس
صيغة الوصف المستخدَمة في _create_clearing_settlement_voucher / routes.py،
مؤكَّدة بفحص سند حقيقي AV-2026-00214 مباشرة):
  - مدين 757 (بنك الرياض): الصافي بعد العمولة وضريبتها
  - مدين 845 (رسوم الدفع الإلكتروني/شبكة مدى): العمولة (0.8%)
  - مدين 773 (ضريبة عمولات نقاط البيع المدفوعة): ضريبة العمولة (15%)
  - دائن 777 (مدى): الإجمالي الكامل 3600.00 -- إقفال هذا المبلغ من حساب مدى

ضمان أمان: يتحقّق أن سند الخطوة 1 (AV-2026-00215) موجود فعلاً قبل
المتابعة (وإلا فالـ3600 قد لا تكون في 777 أصلاً)، يتحقّق أن رصيد حساب
777 الفعلي يكفي 3600.00، ويتحقّق عبر بحث في Voucher.notes أن خطوة 2 هذه
بالذات لم تُنفَّذ من قبل (idempotent).

الوضع الافتراضي: DRY RUN. --apply للتنفيذ الفعلي.

تشغيل:
    docker cp backend/fix_misrouted_noncash_payments_to_cash.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/fix_misrouted_noncash_payments_to_cash.py            # dry run
    docker exec yasargold-backend python backend/fix_misrouted_noncash_payments_to_cash.py --apply     # تنفيذ فعلي
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

ORIGINAL_VOUCHER_NUMBER = 'RV-2026-00976'
INVOICE_NUMBER = 'SELL-2026-847'
STEP1_VOUCHER_NUMBER = 'AV-2026-00215'  # 755 -> 777، نُفِّذ فعلاً، لا يُعاد هنا

MADA_ACCOUNT_ID = 777            # مدى (حيث تجلس الـ3600 الآن، بعد الخطوة 1)
BANK_ACCOUNT_ID = 757             # ح/جاري بنك الرياض (الوجهة الصحيحة الفعلية)
FEE_EXPENSE_ACCOUNT_ID = 845      # رسوم الدفع الإلكتروني (شبكة/مدى)
COMMISSION_VAT_ACCOUNT_ID = 773   # ضريبة عمولات نقاط البيع (مدفوعة)

GROSS_AMOUNT = 3600.00
COMMISSION_RATE = 0.8   # مدى -- PaymentMethod.id=10، نفس النسبة الحالية المستخدَمة في كل تسوياتها
VAT_RATE = 0.15

FEE_AMOUNT = round(GROSS_AMOUNT * COMMISSION_RATE / 100.0, 2)
FEE_VAT = round(FEE_AMOUNT * VAT_RATE, 2)
NET_AMOUNT = round(GROSS_AMOUNT - FEE_AMOUNT - FEE_VAT, 2)

AFFECTED_ACCOUNTS = [MADA_ACCOUNT_ID, BANK_ACCOUNT_ID, FEE_EXPENSE_ACCOUNT_ID, COMMISSION_VAT_ACCOUNT_ID]


def run(apply: bool):
    with app.app_context():
        from routes import generate_voucher_number, create_journal_entry_from_voucher

        run_dt = datetime.now(timezone.utc)
        print(f"{'تطبيق فعلي' if apply else 'DRY RUN — لن يُحفظ شيء في قاعدة البيانات'}")
        print(f"تاريخ التنفيذ: {run_dt.isoformat()}\n")
        print(f"إجمالي: {GROSS_AMOUNT:.2f} | عمولة: {FEE_AMOUNT:.2f} | ضريبة العمولة: {FEE_VAT:.2f} | صافي: {NET_AMOUNT:.2f}\n")

        balances_before = live_balances_by_account_ids(AFFECTED_ACCOUNTS)
        print("أرصدة فعلية قبل التصحيح:")
        for acc_id in AFFECTED_ACCOUNTS:
            print(f"  حساب #{acc_id}: {balances_before.get(acc_id, {}).get('cash', 0.0):.2f}")
        print()

        step1_voucher = Voucher.query.filter_by(voucher_number=STEP1_VOUCHER_NUMBER).first()
        if step1_voucher is None:
            print(f"❌ توقّف: سند الخطوة 1 ({STEP1_VOUCHER_NUMBER}, نقل 755->777) غير موجود -- "
                  f"الـ3600 قد لا تكون في حساب مدى (777) أصلاً. لا تنفيذ.")
            return

        mada_balance = float(balances_before.get(MADA_ACCOUNT_ID, {}).get('cash', 0.0))
        if mada_balance < GROSS_AMOUNT - 0.01:
            print(f"❌ توقّف: رصيد حساب مدى (777) الفعلي ({mada_balance:.2f}) أقل من المبلغ المطلوب ({GROSS_AMOUNT:.2f}).")
            return

        already_corrected = next(
            (v for v in Voucher.query.filter(Voucher.voucher_type == 'adjustment', Voucher.notes.isnot(None)).all()
             if v.notes and '"step": "2_mada_to_bank"' in v.notes and ORIGINAL_VOUCHER_NUMBER in v.notes),
            None,
        )
        if already_corrected is not None:
            print(f"❌ توقّف: تصحيح الخطوة 2 موجود بالفعل ({already_corrected.voucher_number}, id={already_corrected.id}).")
            return

        print(f"✓ {ORIGINAL_VOUCHER_NUMBER} ({INVOICE_NUMBER}) -- الخطوة 2: نقل من مدى (777) إلى البنك\n"
              f"   مدين #{BANK_ACCOUNT_ID} (بنك الرياض) {NET_AMOUNT:.2f}\n"
              f"   مدين #{FEE_EXPENSE_ACCOUNT_ID} (عمولة) {FEE_AMOUNT:.2f}\n"
              f"   مدين #{COMMISSION_VAT_ACCOUNT_ID} (ضريبة العمولة) {FEE_VAT:.2f}\n"
              f"   دائن #{MADA_ACCOUNT_ID} (مدى) {GROSS_AMOUNT:.2f}\n")

        if not apply:
            print("(DRY RUN) لتطبيق التغيير فعليًا أضف --apply")
            db.session.rollback()
            return

        voucher_number = generate_voucher_number('adjustment', voucher_date=run_dt)
        voucher = Voucher(
            voucher_number=voucher_number,
            voucher_type='adjustment',
            date=run_dt,
            # NOTE: create_journal_entry_from_voucher copies this into
            # JournalEntry.description, which is VARCHAR(200) in production
            # (Voucher.description itself is unrestricted Text) -- keep
            # this short; full context lives in `notes`.
            description=(
                f'تسوية مدى -> بنك: {ORIGINAL_VOUCHER_NUMBER} ({INVOICE_NUMBER}) '
                f'-- استكمال تصحيح توجيه (الخطوة 2 من 2)'
            ),
            notes=json.dumps({
                'source': 'fix_misrouted_noncash_payments_to_cash',
                'step': '2_mada_to_bank',
                'reason': (
                    f'Step 2 of 2: moves {GROSS_AMOUNT} from مدى clearing (777) to بنك الرياض (757), '
                    f'completing the correction whose step 1 ({STEP1_VOUCHER_NUMBER}) moved it from cash '
                    '(755) to مدى (777). User confirmed against the real bank statement that this amount '
                    'already settled to the bank in reality, so it is not "pending transfer" -- leaving '
                    'it in 777 would misstate it as still awaiting settlement. Structured exactly like a '
                    'normal clearing-settlement voucher (gross/fee/vat/net split, same accounts as '
                    '_create_clearing_settlement_voucher, verified against real voucher AV-2026-00214).'
                ),
                'original_voucher_number': ORIGINAL_VOUCHER_NUMBER,
                'invoice_number': INVOICE_NUMBER,
                'step1_voucher_number': STEP1_VOUCHER_NUMBER,
                'gross_amount': GROSS_AMOUNT,
                'fee_amount': FEE_AMOUNT,
                'fee_vat': FEE_VAT,
                'net_amount': NET_AMOUNT,
            }, ensure_ascii=False),
            created_by='admin',
            status='approved',
            approved_by='admin',
            approved_at=run_dt,
            amount_cash=GROSS_AMOUNT,
            amount_gold=0.0,
        )
        db.session.add(voucher)
        db.session.flush()

        db.session.add(VoucherAccountLine(
            voucher_id=voucher.id, account_id=BANK_ACCOUNT_ID, line_type='debit',
            amount_type='cash', amount=NET_AMOUNT,
            description='إيداع صافي تسوية مستحقات إلى خزينة بنك الرياض',
        ))
        db.session.add(VoucherAccountLine(
            voucher_id=voucher.id, account_id=FEE_EXPENSE_ACCOUNT_ID, line_type='debit',
            amount_type='cash', amount=FEE_AMOUNT,
            description='عمولة تحصيل (صافي)',
        ))
        db.session.add(VoucherAccountLine(
            voucher_id=voucher.id, account_id=COMMISSION_VAT_ACCOUNT_ID, line_type='debit',
            amount_type='cash', amount=FEE_VAT,
            description='ضريبة قيمة مضافة على عمولة التحصيل',
        ))
        db.session.add(VoucherAccountLine(
            voucher_id=voucher.id, account_id=MADA_ACCOUNT_ID, line_type='credit',
            amount_type='cash', amount=GROSS_AMOUNT,
            description=f'إقفال مستحقات التحصيل -- {ORIGINAL_VOUCHER_NUMBER} ({INVOICE_NUMBER})',
        ))
        db.session.flush()

        journal_entry = create_journal_entry_from_voucher(voucher)
        if journal_entry:
            voucher.journal_entry_id = journal_entry.id

        Account.query.get(BANK_ACCOUNT_ID).update_balance(cash_amount=NET_AMOUNT)
        Account.query.get(FEE_EXPENSE_ACCOUNT_ID).update_balance(cash_amount=FEE_AMOUNT)
        Account.query.get(COMMISSION_VAT_ACCOUNT_ID).update_balance(cash_amount=FEE_VAT)
        Account.query.get(MADA_ACCOUNT_ID).update_balance(cash_amount=-GROSS_AMOUNT)

        report = {
            'run_at': run_dt.isoformat(),
            'applied': True,
            'original_voucher_number': ORIGINAL_VOUCHER_NUMBER,
            'invoice_number': INVOICE_NUMBER,
            'step1_voucher_number': STEP1_VOUCHER_NUMBER,
            'correction_voucher_id': voucher.id,
            'correction_voucher_number': voucher.voucher_number,
            'journal_entry_id': voucher.journal_entry_id,
            'gross_amount': GROSS_AMOUNT,
            'fee_amount': FEE_AMOUNT,
            'fee_vat': FEE_VAT,
            'net_amount': NET_AMOUNT,
            'balances_before': balances_before,
        }
        reports_dir = os.path.join(os.path.dirname(__file__), 'reports')
        os.makedirs(reports_dir, exist_ok=True)
        report_path = os.path.join(
            reports_dir,
            f"fix_misrouted_noncash_payments_to_cash_{run_dt.strftime('%Y%m%dT%H%M%SZ')}_applied.json",
        )

        db.session.commit()

        balances_after = live_balances_by_account_ids(AFFECTED_ACCOUNTS)
        report['balances_after'] = balances_after
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        print(f"✅ {ORIGINAL_VOUCHER_NUMBER} خطوة 2 -> سند تصحيح {voucher.voucher_number} (id={voucher.id}), القيد JE#{voucher.journal_entry_id}\n")
        print("أرصدة فعلية بعد التصحيح:")
        for acc_id in AFFECTED_ACCOUNTS:
            print(f"  حساب #{acc_id}: {balances_after.get(acc_id, {}).get('cash', 0.0):.2f}")
        print(f"\nتم كتابة التقرير: {report_path}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    run(apply=args.apply)
