"""
fix_sale_invoice_qty_bug_per_karat.py
========================================
تسوية تاريخية واحدة (لكل عيار على حدة) لتأثير "مشكلة الوزن×الكمية" في
184 فاتورة "بيع"/ذهب جديد على حساب 760 (مخزون الذهب المعروض للبيع وزني،
مرتبط بخزينة [30]).

لا تُعدّل أي قيد تاريخي لأي فاتورة. بدل ذلك:

  1. تحسب لكل عيار (18/21/22/24) "الفرق" = |صافي القيد المسجّل| - |الوزن
     الصحيح من الأصناف الحالية (بدون ضرب بالكمية)|، مجمّعاً على كل
     الفواتير المتأثرة (184 فاتورة).
  2. تُنشئ قيد محاسبي واحد:
       - مدين حساب 760 (مخزون الذهب المعروض للبيع وزني) بالفرق لكل عيار
       - دائن حساب 7600 (فروقات تقييم وزنية) بنفس المبالغ لكل عيار
     ثم تُعيد حساب أرصدة الحسابين من القيود.
  3. تُنشئ حركة SafeBoxTransaction واحدة لخزينة [30]، direction='in'،
     بنفس الفرق لكل عيار (18/21/22/24 كما هي، بدون تحويل لعيار رئيسي).

التسمية:
  ref_type = 'historical_gold_reconciliation_per_karat'
  وصف القيد ومذكرات الحركة تحتوي تاريخ التنفيذ ومصدر الفرق، لتمييزها
  مستقبلاً عن أي حركة تشغيلية فعلية.

قبل أي --apply يُكتب تقرير كامل (نص + JSON في backend/reports/) يحتوي:
  اسم الخزينة، الفرق قبل الإصلاح لكل عيار، رصيد حساب 760 وسند صرف
  الخزينة [30] قبل وبعد لكل عيار، وتاريخ التنفيذ.

تشغيل:
    docker cp backend/fix_sale_invoice_qty_bug_per_karat.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/fix_sale_invoice_qty_bug_per_karat.py            # dry run + تقرير
    docker exec yasargold-backend python backend/fix_sale_invoice_qty_bug_per_karat.py --apply     # تطبيق فعلي + تقرير

الوضع الافتراضي: DRY RUN (لا يُحفظ شيء في قاعدة البيانات، لكن التقرير يُكتب دائمًا).
"""

import os
import sys
import json
import argparse
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from sqlalchemy import func
from models import db, Account, SafeBox, SafeBoxTransaction, JournalEntry, JournalEntryLine, Invoice, InvoiceItem
from routes import _generate_journal_entry_number


KARATS = (18, 21, 22, 24)
ACCOUNT_NUMBER_INVENTORY_NEW = '71300'   # مخزون الذهب المعروض للبيع وزني
ACCOUNT_NUMBER_VALUATION_DIFF = '733'    # فروقات تقييم الذهب وزني
SAFE_BOX_ID = 30
REF_TYPE = 'historical_gold_reconciliation_per_karat'
EPS = 1e-9


def compute_excess_by_karat(account_id: int):
    """نفس منطق inspect_qty_bug_per_karat.py: الفرق لكل عيار عبر الفواتير المتأثرة."""
    from routes import convert_to_main_karat

    lines = (
        JournalEntryLine.query
        .join(JournalEntry)
        .filter(
            JournalEntryLine.account_id == account_id,
            JournalEntry.is_deleted == False,
            JournalEntryLine.is_deleted == False,
            JournalEntry.is_posted == True,
            JournalEntry.reference_type == 'invoice',
        )
        .all()
    )

    je_by_inv = defaultdict(list)
    for line in lines:
        entry = line.journal_entry
        inv_id = getattr(entry, 'reference_id', None)
        je_by_inv[inv_id].append(line)

    excess_by_karat = defaultdict(float)
    affected_invoice_numbers = []

    for inv_id, je_lines in je_by_inv.items():
        inv = Invoice.query.get(inv_id) if inv_id else None
        if not inv:
            continue
        if getattr(inv, 'invoice_type', None) != 'بيع' or (getattr(inv, 'gold_type', None) or 'new') != 'new':
            continue

        je_cur = {k: 0.0 for k in KARATS}
        for l in je_lines:
            for k in KARATS:
                je_cur[k] += (getattr(l, f'debit_{k}k') or 0) - (getattr(l, f'credit_{k}k') or 0)

        items = InvoiceItem.query.filter_by(invoice_id=inv_id).all()
        correct = {k: 0.0 for k in KARATS}
        for it in items:
            k = int(round(float(it.karat or 0)))
            w = float(it.weight or 0)
            if k not in KARATS or w <= 0:
                continue
            correct[k] += w

        je_main = sum(convert_to_main_karat(je_cur[k], k) for k in KARATS)
        correct_main = sum(convert_to_main_karat(correct[k], k) for k in KARATS)
        if abs(abs(je_main) - correct_main) < 0.01:
            continue  # غير متأثرة

        affected_invoice_numbers.append(inv.invoice_number)
        for k in KARATS:
            excess_k = abs(je_cur[k]) - correct[k]
            if abs(excess_k) > EPS:
                excess_by_karat[k] += excess_k

    return excess_by_karat, affected_invoice_numbers


def ledger_balance_by_karat(safe_box_id: int):
    q = SafeBoxTransaction.query.filter_by(safe_box_id=safe_box_id)

    def _sum(field, direction):
        col = getattr(SafeBoxTransaction, field)
        return float(
            q.with_entities(func.coalesce(func.sum(col), 0.0))
            .filter(SafeBoxTransaction.direction == direction)
            .scalar() or 0.0
        )

    return {k: _sum(f'weight_{k}k', 'in') - _sum(f'weight_{k}k', 'out') for k in KARATS}


def run(apply: bool):
    with app.app_context():
        run_dt = datetime.now(timezone.utc)
        print(f"\n{'=' * 60}")
        print(f"{'تطبيق فعلي' if apply else 'DRY RUN — لن يُحفظ شيء في قاعدة البيانات'}")
        print(f"تاريخ التنفيذ: {run_dt.isoformat()}")
        print(f"{'=' * 60}\n")

        acc_inv = Account.query.filter_by(account_number=ACCOUNT_NUMBER_INVENTORY_NEW).first()
        acc_diff = Account.query.filter_by(account_number=ACCOUNT_NUMBER_VALUATION_DIFF).first()
        sb = SafeBox.query.get(SAFE_BOX_ID)

        if not acc_inv or not acc_diff or not sb:
            print("خطأ: لم يتم العثور على أحد الحسابات/الخزينة المطلوبة.")
            print(f"  account[{ACCOUNT_NUMBER_INVENTORY_NEW}]={acc_inv}, "
                  f"account[{ACCOUNT_NUMBER_VALUATION_DIFF}]={acc_diff}, safe_box[{SAFE_BOX_ID}]={sb}")
            return

        excess_by_karat, affected_invoice_numbers = compute_excess_by_karat(acc_inv.id)

        balance_before = {k: getattr(acc_inv, f'balance_{k}k') for k in KARATS}
        ledger_before = ledger_balance_by_karat(SAFE_BOX_ID)

        report = {
            'run_at': run_dt.isoformat(),
            'applied': apply,
            'ref_type': REF_TYPE,
            'safe_box_id': SAFE_BOX_ID,
            'safe_box_name': sb.name,
            'account_inventory_id': acc_inv.id,
            'account_inventory_number': acc_inv.account_number,
            'account_valuation_diff_id': acc_diff.id,
            'account_valuation_diff_number': acc_diff.account_number,
            'affected_invoice_count': len(affected_invoice_numbers),
            'affected_invoice_numbers': affected_invoice_numbers,
            'by_karat': {},
        }

        print(f"الخزينة: [{SAFE_BOX_ID}] {sb.name}")
        print(f"عدد الفواتير المتأثرة: {len(affected_invoice_numbers)}")
        print(f"حساب المخزون: [{acc_inv.id}] {acc_inv.account_number} {acc_inv.name}")
        print(f"حساب فروقات التقييم: [{acc_diff.id}] {acc_diff.account_number} {acc_diff.name}")
        print()

        has_diff = False
        for k in KARATS:
            diff = round(excess_by_karat.get(k, 0.0), 6)
            if abs(diff) < EPS:
                report['by_karat'][k] = {
                    'diff': 0.0,
                    'account_balance_before': round(balance_before[k], 6),
                    'account_balance_after': round(balance_before[k], 6),
                    'safebox_ledger_before': round(ledger_before[k], 6),
                    'safebox_ledger_after': round(ledger_before[k], 6),
                }
                continue

            has_diff = True
            acc_after = round(balance_before[k] + diff, 6)
            led_after = round(ledger_before[k] + diff, 6)

            report['by_karat'][k] = {
                'diff': diff,
                'account_balance_before': round(balance_before[k], 6),
                'account_balance_after': acc_after,
                'safebox_ledger_before': round(ledger_before[k], 6),
                'safebox_ledger_after': led_after,
            }

            print(f"  عيار {k}:")
            print(f"    الفرق (يجب إضافته)            = {diff:>14,.3f}")
            print(f"    رصيد حساب 760 قبل             = {balance_before[k]:>14,.3f}")
            print(f"    رصيد حساب 760 بعد             = {acc_after:>14,.3f}")
            print(f"    سند صرف [{SAFE_BOX_ID}] قبل           = {ledger_before[k]:>14,.3f}")
            print(f"    سند صرف [{SAFE_BOX_ID}] بعد           = {led_after:>14,.3f}")
            print()

        if not has_diff:
            print("لا يوجد فرق - لا حاجة لأي تسوية.")

        # Always write the report (dry run or apply)
        reports_dir = os.path.join(os.path.dirname(__file__), 'reports')
        os.makedirs(reports_dir, exist_ok=True)
        report_path = os.path.join(
            reports_dir,
            f"sale_invoice_qty_bug_per_karat_{run_dt.strftime('%Y%m%dT%H%M%SZ')}"
            f"{'_applied' if apply else '_dryrun'}.json"
        )
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\nتم كتابة التقرير: {report_path}")

        if not has_diff:
            return

        if apply:
            notes = (
                f"تسوية تاريخية لكل عيار على حدة (historical_gold_reconciliation_per_karat) "
                f"بتاريخ {run_dt.date().isoformat()} — ناتجة عن خطأ في {len(affected_invoice_numbers)} "
                f"فاتورة بيع/ذهب جديد (~يناير-مارس 2026) كان فيها صافي القيد على حساب "
                f"{acc_inv.account_number} يساوي وزن×الكمية بدل الوزن فقط. "
                f"هذه حركة محاسبية لتسوية الفروقات المتراكمة، وليست حركة تشغيلية فعلية."
            )

            je_date = datetime.utcnow()
            je = JournalEntry(
                entry_number=_generate_journal_entry_number('JE', je_date),
                date=je_date,
                description=f"تسوية تاريخية - فروقات تقييم وزني ناتجة عن تضخيم وزن فواتير البيع ({REF_TYPE})",
                entry_type='عادي',
                reference_type=None,
                reference_id=None,
                reference_number=None,
                created_by='admin',
                is_draft=False,
                is_posted=True,
                posted_at=je_date,
                posted_by='admin',
            )
            db.session.add(je)
            db.session.flush()

            line_inv = JournalEntryLine(
                journal_entry_id=je.id,
                account_id=acc_inv.id,
                description=notes,
            )
            line_diff = JournalEntryLine(
                journal_entry_id=je.id,
                account_id=acc_diff.id,
                description=notes,
            )
            for k in KARATS:
                diff = round(excess_by_karat.get(k, 0.0), 6)
                if abs(diff) < EPS:
                    continue
                setattr(line_inv, f'debit_{k}k', diff)
                setattr(line_diff, f'credit_{k}k', diff)

            db.session.add(line_inv)
            db.session.add(line_diff)

            from routes import _recalculate_account_balances_for_accounts
            _recalculate_account_balances_for_accounts([acc_inv.id, acc_diff.id])

            tx = SafeBoxTransaction(
                safe_box_id=SAFE_BOX_ID,
                ref_type=REF_TYPE,
                ref_id=je.id,
                invoice_id=None,
                direction='in',
                amount_cash=0.0,
                weight_18k=round(excess_by_karat.get(18, 0.0), 6),
                weight_21k=round(excess_by_karat.get(21, 0.0), 6),
                weight_22k=round(excess_by_karat.get(22, 0.0), 6),
                weight_24k=round(excess_by_karat.get(24, 0.0), 6),
                notes=notes,
                created_by='admin',
            )
            db.session.add(tx)

            db.session.commit()
            print(f"\n✅ تم الحفظ. قيد محاسبي: {je.entry_number}، حركة سند صرف لخزينة [{SAFE_BOX_ID}].")
        else:
            db.session.rollback()
            print("\n(DRY RUN) لتطبيق التغييرات فعليًا أضف --apply")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    run(apply=args.apply)
