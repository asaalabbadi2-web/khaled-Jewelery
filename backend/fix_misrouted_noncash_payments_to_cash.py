"""
fix_misrouted_noncash_payments_to_cash.py
=============================================
تصحيح بيانات حقيقي بطلب صريح من المستخدم: 6 سندات حقيقية في الإنتاج سجّلت
دفعة فاتورة بوسيلة دفع غير نقدية (مدى/تحويل) في حساب الصندوق النقدي
الرئيسي (755) بدل حساب الوسيلة الصحيحة -- بينما سجل InvoicePayment نفسه
الوسيلة الصحيحة دائماً (لا خطأ في تصنيف الدفعة، الخطأ فقط في حساب القيد).

السبب الجذري المؤكَّد بالكود: race condition في
_loadSafeBoxesForPaymentMethod (sales_invoice_screen_v2.dart و
purchase_invoice_screen.dart بشكل مستقل) -- تم تصحيحه في كومِت منفصل.
هذا السكريبت يعالج الأثر التاريخي فقط (الفواتير الست المتأثرة قبل التصحيح).

السندات الستة (مكتشفة بمسح شامل لكل سندات reference_type=invoice، 1356
سنداً، عبر /tmp/scan_mismatches.py):
  1. RV-2026-00419  (voucher_id=824,  JE#1813) مدى   1130.00  SELL-2026-421
  2. RV-2026-00453  (voucher_id=895,  JE#1986) مدى    620.00  SELL-2026-453
  3. RV-2026-00976  (voucher_id=2139, JE#4124) مدى   3600.00  SELL-2026-847
  4. PV-2026-00226  (voucher_id=977,  JE#2150) تحويل  830.00  BUY-2026-072
  5. PV-2026-00239  (voucher_id=1007, JE#2202) تحويل 19600.00 BUY-2026-080
  6. PV-2026-00240  (voucher_id=1008, JE#2202) تحويل 10000.00 BUY-2026-080

لكل سند: ينشئ سند تعديل (adjustment) مستقل بسطرين متوازنين يعكسان الخطأ
بالضبط، دون لمس القيد الأصلي المرحَّل ولا InvoicePayment ولا
payment_method_id (الذي كان صحيحاً دائماً):
  - استلام (receipt, مدى):  مدين [الحساب الصحيح] / دائن 755 (الصندوق)
  - دفع (payment, تحويل):   مدين 755 (الصندوق) / دائن [الحساب الصحيح]
ثم ينشئ القيد المحاسبي المرتبط عبر create_journal_entry_from_voucher --
نفس الآلية المستخدَمة في كل سندات النظام -- فيحصل تلقائياً على
reference_type='voucher' (ضمن القائمة المسموحة في حارس حسابات المقاصة).

ضمان أمان: قبل أي تعديل، يعيد تحميل السند الأصلي من قاعدة البيانات
ويتحقّق أن أحد سطوره لا يزال يشير فعلاً إلى حساب 755 بنفس المبلغ المتوقَّع
-- يتخطّى (skip) ذلك التصحيح بدل التنفيذ لو وجد أن أحداً صحّحه يدوياً
بالفعل بين وقت التحقيق وتشغيل هذا السكريبت.

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

CASH_ACCOUNT_ID = 755          # صندوق النقدية الرئيسي
MADA_ACCOUNT_ID = 777          # مدى
BANK_TRANSFER_ACCOUNT_ID = 757  # تحويل

# (original_voucher_id, original_voucher_number, invoice_number, direction, amount, correct_account_id, correct_account_name)
#
# NOTE (2026-06-23): RV-2026-00419 (1130, مدى) and RV-2026-00453 (620, مدى)
# were REMOVED from this list on the user's explicit instruction, after
# they compared مدى's account against the real bank statement directly:
# both amounts were already covered by older, separate correction entries
# (the only outstanding difference against the bank statement was the
# 3600 from RV-2026-00976). Re-adding either here without re-confirming
# against the bank statement again would double-correct them.
#
# PV-2026-00226 (830, تحويل) was ALSO removed: the user confirmed this
# voucher's cash account is the correct, original classification --
# tagging it as تحويل-misrouted-to-cash here was a false positive from the
# original detection scan (likely a payment_method_id data issue on
# InvoicePayment itself, not a safe-box routing bug). Out of scope for
# this script.
CORRECTIONS = [
    (2139, 'RV-2026-00976', 'SELL-2026-847', 'in',  3600.00, MADA_ACCOUNT_ID,          'مدى'),
    (1008, 'PV-2026-00240', 'BUY-2026-080',  'out', 10000.00, BANK_TRANSFER_ACCOUNT_ID, 'تحويل'),
]


def run(apply: bool):
    with app.app_context():
        from routes import generate_voucher_number, create_journal_entry_from_voucher

        run_dt = datetime.now(timezone.utc)
        print(f"{'تطبيق فعلي' if apply else 'DRY RUN — لن يُحفظ شيء في قاعدة البيانات'}")
        print(f"تاريخ التنفيذ: {run_dt.isoformat()}\n")

        affected_accounts = {CASH_ACCOUNT_ID, MADA_ACCOUNT_ID, BANK_TRANSFER_ACCOUNT_ID}
        balances_before = live_balances_by_account_ids(list(affected_accounts))
        print("أرصدة فعلية قبل أي تصحيح:")
        for acc_id in affected_accounts:
            print(f"  حساب #{acc_id}: {balances_before.get(acc_id, {}).get('cash', 0.0):.2f}")
        print()

        to_apply = []
        for orig_id, orig_number, inv_number, direction, amount, correct_acc, correct_name in CORRECTIONS:
            orig_voucher = Voucher.query.get(orig_id)
            if orig_voucher is None:
                print(f"⚠️  تخطّي {orig_number}: السند الأصلي (id={orig_id}) غير موجود.")
                continue
            if orig_voucher.voucher_number != orig_number:
                print(f"⚠️  تخطّي {orig_number}: رقم السند لا يطابق (وجدت {orig_voucher.voucher_number}) -- توقّف يدوي مطلوب.")
                continue

            lines = orig_voucher.account_lines.all() if hasattr(orig_voucher.account_lines, 'all') else list(orig_voucher.account_lines)
            cash_line = next((l for l in lines if l.account_id == CASH_ACCOUNT_ID and abs(float(l.amount or 0.0) - amount) < 0.01), None)
            if cash_line is None:
                print(f"⚠️  تخطّي {orig_number}: لم أجد سطراً على حساب 755 بمبلغ {amount:.2f} -- "
                      f"يبدو أن أحداً صحّحه مسبقاً أو تغيّرت البيانات. لا تنفيذ.")
                continue

            # Idempotency: skip if a correcting voucher for this exact original
            # voucher was already created by a previous run of this script.
            already_corrected = (
                Voucher.query
                .filter(Voucher.voucher_type == 'adjustment', Voucher.notes.like(f'%"original_voucher_id": {orig_id}%'))
                .first()
            )
            if already_corrected is not None:
                print(f"⚠️  تخطّي {orig_number}: تصحيح سابق موجود بالفعل "
                      f"({already_corrected.voucher_number}, id={already_corrected.id}) -- لا تنفيذ مكرر.")
                continue

            to_apply.append((orig_voucher, orig_number, inv_number, direction, amount, correct_acc, correct_name))
            debit_acc, credit_acc = (correct_acc, CASH_ACCOUNT_ID) if direction == 'in' else (CASH_ACCOUNT_ID, correct_acc)
            print(f"✓ {orig_number} ({inv_number}, {correct_name}, {amount:.2f}): "
                  f"مدين #{debit_acc} / دائن #{credit_acc}")

        print(f"\n{len(to_apply)} من {len(CORRECTIONS)} تصحيحات جاهزة للتنفيذ.\n")

        if not apply:
            print("(DRY RUN) لتطبيق التغييرات فعليًا أضف --apply")
            db.session.rollback()
            return

        if not to_apply:
            print("لا شيء للتنفيذ.")
            return

        created = []
        for orig_voucher, orig_number, inv_number, direction, amount, correct_acc, correct_name in to_apply:
            debit_acc_id, credit_acc_id = (correct_acc, CASH_ACCOUNT_ID) if direction == 'in' else (CASH_ACCOUNT_ID, correct_acc)

            voucher_number = generate_voucher_number('adjustment', voucher_date=run_dt)
            voucher = Voucher(
                voucher_number=voucher_number,
                voucher_type='adjustment',
                date=run_dt,
                # NOTE: create_journal_entry_from_voucher copies this into
                # JournalEntry.description, which is VARCHAR(200) in
                # production (Voucher.description itself is unrestricted
                # Text) -- keep this short; full context lives in `notes`.
                description=(
                    f'تصحيح توجيه دفعة {correct_name}: {orig_number} ({inv_number}) '
                    f'إلى حساب {correct_name} الصحيح'
                ),
                notes=json.dumps({
                    'source': 'fix_misrouted_noncash_payments_to_cash',
                    'reason': (
                        'race condition in _loadSafeBoxesForPaymentMethod sent a stale '
                        'safe box id when the payment method dropdown was switched quickly; '
                        'fixed in code, this corrects the historical GL effect for this one voucher'
                    ),
                    'original_voucher_id': orig_voucher.id,
                    'original_voucher_number': orig_number,
                    'invoice_number': inv_number,
                    'amount': amount,
                    'correct_account_id': correct_acc,
                }, ensure_ascii=False),
                created_by='admin',
                status='approved',
                approved_by='admin',
                approved_at=run_dt,
                amount_cash=amount,
                amount_gold=0.0,
            )
            db.session.add(voucher)
            db.session.flush()

            db.session.add(VoucherAccountLine(
                voucher_id=voucher.id,
                account_id=debit_acc_id,
                line_type='debit',
                amount_type='cash',
                amount=amount,
                description=f'تصحيح توجيه دفعة {correct_name} -- {orig_number} ({inv_number})',
            ))
            db.session.add(VoucherAccountLine(
                voucher_id=voucher.id,
                account_id=credit_acc_id,
                line_type='credit',
                amount_type='cash',
                amount=amount,
                description=f'تصحيح توجيه دفعة {correct_name} -- {orig_number} ({inv_number})',
            ))
            db.session.flush()

            journal_entry = create_journal_entry_from_voucher(voucher)
            if journal_entry:
                voucher.journal_entry_id = journal_entry.id

            debit_account = Account.query.get(debit_acc_id)
            credit_account = Account.query.get(credit_acc_id)
            if debit_account is not None:
                debit_account.update_balance(cash_amount=amount)
            if credit_account is not None:
                credit_account.update_balance(cash_amount=-amount)

            created.append({
                'original_voucher_number': orig_number,
                'invoice_number': inv_number,
                'amount': amount,
                'correction_voucher_id': voucher.id,
                'correction_voucher_number': voucher.voucher_number,
                'journal_entry_id': voucher.journal_entry_id,
                'debit_account_id': debit_acc_id,
                'credit_account_id': credit_acc_id,
            })
            print(f"✅ {orig_number} -> سند تصحيح {voucher.voucher_number} (id={voucher.id}), "
                  f"القيد JE#{voucher.journal_entry_id}")

        report = {
            'run_at': run_dt.isoformat(),
            'applied': True,
            'corrections': created,
            'balances_before': balances_before,
        }
        reports_dir = os.path.join(os.path.dirname(__file__), 'reports')
        os.makedirs(reports_dir, exist_ok=True)
        report_path = os.path.join(
            reports_dir,
            f"fix_misrouted_noncash_payments_to_cash_{run_dt.strftime('%Y%m%dT%H%M%SZ')}_applied.json",
        )

        db.session.commit()

        balances_after = live_balances_by_account_ids(list(affected_accounts))
        report['balances_after'] = balances_after
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        print(f"\nأرصدة فعلية بعد التصحيح:")
        for acc_id in affected_accounts:
            print(f"  حساب #{acc_id}: {balances_after.get(acc_id, {}).get('cash', 0.0):.2f}")
        print(f"\nتم كتابة التقرير: {report_path}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    run(apply=args.apply)
