"""
fix_av045_ip1003_settlement_line.py
======================================
تصحيح بيانات محدّد ومسنود بالحسابات (لا تقديري) لـ SettlementLine#477.

السياق: AV-2026-00045 (سند 991) سوّى IP 1003 بالكامل (3050.00) في
2026-04-17T07:20:49 دون أن "يرى" أن AV-2026-00044 (سند 990) سوّى منها
2600.00 قبل ذلك بـ1.5 ساعة (2026-04-17T05:44:48) — هذا أنتج تغطية مزدوجة
بقيمة 2600.00 زائدة على IP 1003 (تغطيتها الإجمالية 5650.00 بدل 3050.00
الحقيقية)، وجعل سند 991 غير متّسق ذاتياً (settlement_line_total=3670.00
بينما المُقيَّد فعلياً على الحساب=1070.00 فقط).

التصحيح: تعديل amount_settled لسطر SettlementLine#477 فقط من 3050.00 إلى
450.00 (= 3050.00 - 2600.00، أي حصة سند 991 الحقيقية من IP 1003 بعد طرح ما
سبق أن سوّاه سند 990 بشكل صحيح). بعد التصحيح:
  - IP 1003 إجمالي التغطية: 2600.00 (990) + 450.00 (991) = 3050.00 — يطابق
    قيمتها الحقيقية بالضبط، لا تغطية زائدة ولا ناقصة.
  - سند 991 (AV-045) إجمالي SettlementLine: 450.00 (IP1003) + 620.00
    (IP1009، غير متأثر) = 1070.00 — يطابق المُقيَّد فعلياً على الحساب
    (1070.00) بالضبط، يصبح متّسقاً ذاتياً.

لا تغيير على: amount_cash لأي سند، VoucherAccountLine، JournalEntry، أو
أي رصيد حساب — هذا تصحيح لجدول تتبّع SettlementLine فقط (أي دفعة ارتبطت
بأي سند)، لا للقيد المحاسبي نفسه.

ضمان أمان: يرفض السكربت العمل (حتى في dry-run) إن لم يجد بالضبط:
  SettlementLine.id == 477
  voucher_id == 991
  invoice_payment_id == 1003
  amount_settled == 3050.00 (ضمن سنت واحد)

الوضع الافتراضي: DRY RUN (لا يُحفظ شيء، يُطبع before/after فقط، ويُكتب
تقرير JSON دائماً بصرف النظر عن --apply).

تشغيل:
    docker cp backend/fix_av045_ip1003_settlement_line.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/fix_av045_ip1003_settlement_line.py            # dry run
    docker exec yasargold-backend python backend/fix_av045_ip1003_settlement_line.py --apply     # تطبيق فعلي
"""

import os
import sys
import json
import argparse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, SettlementLine, Voucher

SL_ID = 477
EXPECTED_VOUCHER_ID = 991
EXPECTED_IP_ID = 1003
EXPECTED_AMOUNT = 3050.00
NEW_AMOUNT = 450.00
EPS = 0.01


def run(apply: bool):
    with app.app_context():
        run_dt = datetime.now(timezone.utc)

        sl477 = SettlementLine.query.get(SL_ID)
        if not sl477:
            print(f"❌ توقّف: SettlementLine#{SL_ID} غير موجودة.")
            return
        if sl477.voucher_id != EXPECTED_VOUCHER_ID:
            print(f"❌ توقّف: voucher_id={sl477.voucher_id} لا يطابق المتوقَّع ({EXPECTED_VOUCHER_ID}).")
            return
        if sl477.invoice_payment_id != EXPECTED_IP_ID:
            print(f"❌ توقّف: invoice_payment_id={sl477.invoice_payment_id} لا يطابق المتوقَّع ({EXPECTED_IP_ID}).")
            return
        if abs(sl477.amount_settled - EXPECTED_AMOUNT) > EPS:
            print(f"❌ توقّف: amount_settled={sl477.amount_settled} لا يطابق المتوقَّع ({EXPECTED_AMOUNT}).")
            return

        voucher991 = Voucher.query.get(EXPECTED_VOUCHER_ID)
        sl_before_total_991 = round(
            sum(s.amount_settled for s in SettlementLine.query.filter_by(voucher_id=EXPECTED_VOUCHER_ID).all()), 2
        )
        ip1003_before_total = round(
            sum(s.amount_settled for s in SettlementLine.query.filter_by(invoice_payment_id=EXPECTED_IP_ID).all()), 2
        )

        print(f"{'تطبيق فعلي' if apply else 'DRY RUN — لن يُحفظ شيء في قاعدة البيانات'}")
        print(f"تاريخ التنفيذ: {run_dt.isoformat()}\n")

        print("Before:")
        print(f"  SettlementLine#{SL_ID} = {sl477.amount_settled:.2f}")
        print(f"  IP{EXPECTED_IP_ID} total covered = {ip1003_before_total:.2f}")
        print(f"  Voucher {voucher991.voucher_number} total settlement lines = {sl_before_total_991:.2f}")
        print(f"  Voucher {voucher991.voucher_number} credited_on_account = {voucher991.amount_cash:.2f}\n")

        if apply:
            sl477.amount_settled = NEW_AMOUNT

        sl_after_total_991 = round(sl_before_total_991 - EXPECTED_AMOUNT + NEW_AMOUNT, 2)
        ip1003_after_total = round(ip1003_before_total - EXPECTED_AMOUNT + NEW_AMOUNT, 2)

        print("After:")
        print(f"  SettlementLine#{SL_ID} = {NEW_AMOUNT:.2f}")
        print(f"  IP{EXPECTED_IP_ID} total covered = {ip1003_after_total:.2f}")
        print(f"  Voucher {voucher991.voucher_number} total settlement lines = {sl_after_total_991:.2f}")
        print(f"  Voucher {voucher991.voucher_number} credited_on_account = {voucher991.amount_cash:.2f} (unchanged)\n")

        report = {
            'run_at': run_dt.isoformat(),
            'applied': apply,
            'settlement_line_id': SL_ID,
            'voucher_id': EXPECTED_VOUCHER_ID,
            'voucher_number': voucher991.voucher_number,
            'invoice_payment_id': EXPECTED_IP_ID,
            'before': {
                'settlement_line_amount': EXPECTED_AMOUNT,
                'ip_total_covered': ip1003_before_total,
                'voucher_settlement_line_total': sl_before_total_991,
                'voucher_credited_on_account': voucher991.amount_cash,
            },
            'after': {
                'settlement_line_amount': NEW_AMOUNT,
                'ip_total_covered': ip1003_after_total,
                'voucher_settlement_line_total': sl_after_total_991,
                'voucher_credited_on_account': voucher991.amount_cash,
            },
        }

        reports_dir = os.path.join(os.path.dirname(__file__), 'reports')
        os.makedirs(reports_dir, exist_ok=True)
        report_path = os.path.join(
            reports_dir,
            f"fix_av045_ip1003_settlement_line_{run_dt.strftime('%Y%m%dT%H%M%SZ')}"
            f"{'_applied' if apply else '_dryrun'}.json",
        )
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"تم كتابة التقرير: {report_path}")

        if apply:
            db.session.commit()
            print(f"\n✅ تم الحفظ. SettlementLine#{SL_ID}.amount_settled = {NEW_AMOUNT:.2f}")
        else:
            db.session.rollback()
            print("\n(DRY RUN) لتطبيق التغيير فعليًا أضف --apply")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    run(apply=args.apply)
