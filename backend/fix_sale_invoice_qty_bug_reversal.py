"""
fix_sale_invoice_qty_bug_reversal.py
=======================================
تسوية "مشكلة الوزن×الكمية" في 184 فاتورة "بيع"/ذهب جديد، عبر قيد عكسي
*متناسب* لكل فاتورة على حدة - بدل قيد تسوية مجمّع واحد.

لماذا هذا الأسلوب (بدلاً من قيد واحد مجمّع على حساب 760 وحده):
  القيد الأصلي لكل فاتورة متأثرة يحتوي 4 أسطر وزن (أو أكثر) لكل عيار،
  كلها مُضخَّمة بنفس "المعامل" (مثال: حساب 760 = 77.6، الوزن الصحيح = 38.8،
  المعامل = 0.5):
    - [760] مخزون الذهب المعروض للبيع وزني        (دائن، يقل المخزون)
    - [822] إيرادات النشاط وزني / [1140] مبيعات ذهب جديد وزني (دائن)
    - [826] تكلفة المبيعات وزني                    (مدين)
    - [71200xxx] أرصدة ذهب العملاء - <عميل>        (مدين، رصيد العميل الوزني)

  بإنشاء قيد عكسي *متناسب* (نفس الأسطر، بنفس النسبة، بعكس الاتجاه)، يُصحَّح
  المخزون ورصيد العميل الوزني وحسابات الإيراد/التكلفة الوزنية معًا، والقيد
  يبقى متوازناً تلقائياً لأنه انعكاس متناسب لقيد متوازن أصلاً. تم التحقق من
  هذا الافتراض على كل الفواتير الـ184 عبر inspect_qty_bug_reversal_plan.py
  (لا توجد حالات شاذة).

كل فاتورة متأثرة تحصل على:
  1. قيد محاسبي عكسي واحد (entry_type='عادي', reference_type='invoice',
     reference_id=<invoice_id>) يحتوي الأسطر العكسية المتناسبة.
  2. حركة SafeBoxTransaction واحدة على خزينة [30]، مرتبطة بـ invoice_id
     ومعرّف القيد العكسي، بمقدار التصحيح في حساب 760 لهذه الفاتورة.

التسمية:
  ref_type = 'hist_gold_recon_invoice_reversal'

قبل أي --apply يُكتب تقرير كامل (JSON في backend/reports/) يحتوي تفاصيل
كل فاتورة (المعامل لكل عيار، الأسطر العكسية) + ملخص إجمالي (رصيد حساب 760
وسند صرف خزينة [30] قبل/بعد لكل عيار) وتاريخ التنفيذ.

تشغيل:
    docker cp backend/fix_sale_invoice_qty_bug_reversal.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/fix_sale_invoice_qty_bug_reversal.py            # dry run + تقرير
    docker exec yasargold-backend python backend/fix_sale_invoice_qty_bug_reversal.py --apply     # تطبيق فعلي + تقرير

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
from routes import convert_to_main_karat, _generate_journal_entry_number, _recalculate_account_balances_for_accounts


KARATS = (18, 21, 22, 24)
ACCOUNT_NUMBER_INVENTORY_NEW = '71300'   # مخزون الذهب المعروض للبيع وزني
SAFE_BOX_ID = 30
REF_TYPE = 'hist_gold_recon_invoice_reversal'  # <= 40 chars (SafeBoxTransaction.ref_type limit)
EPS = 1e-6


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
        sb = SafeBox.query.get(SAFE_BOX_ID)
        if not acc_inv or not sb:
            print("خطأ: لم يتم العثور على حساب المخزون أو الخزينة.")
            return

        balance_before = {k: getattr(acc_inv, f'balance_{k}k') for k in KARATS}
        ledger_before = ledger_balance_by_karat(SAFE_BOX_ID)

        # All JE lines on account 760, grouped by invoice
        lines_760 = (
            JournalEntryLine.query
            .join(JournalEntry)
            .filter(
                JournalEntryLine.account_id == acc_inv.id,
                JournalEntry.is_deleted == False,
                JournalEntryLine.is_deleted == False,
                JournalEntry.is_posted == True,
                JournalEntry.reference_type == 'invoice',
            )
            .all()
        )

        je_by_inv = defaultdict(list)
        for line in lines_760:
            entry = line.journal_entry
            inv_id = getattr(entry, 'reference_id', None)
            je_by_inv[inv_id].append((line, entry.id))

        je_date = datetime.utcnow()
        invoice_rows = []
        acc_760_delta = {k: 0.0 for k in KARATS}
        touched_account_ids = set()

        for inv_id, line_je_pairs in je_by_inv.items():
            inv = Invoice.query.get(inv_id) if inv_id else None
            if not inv:
                continue
            if getattr(inv, 'invoice_type', None) != 'بيع' or (getattr(inv, 'gold_type', None) or 'new') != 'new':
                continue

            je_ids = set(je_id for _, je_id in line_je_pairs)

            je_cur_760 = {k: 0.0 for k in KARATS}
            for l, _ in line_je_pairs:
                for k in KARATS:
                    je_cur_760[k] += (getattr(l, f'debit_{k}k') or 0) - (getattr(l, f'credit_{k}k') or 0)

            items = InvoiceItem.query.filter_by(invoice_id=inv_id).all()
            correct = {k: 0.0 for k in KARATS}
            for it in items:
                k = int(round(float(it.karat or 0)))
                w = float(it.weight or 0)
                if k not in KARATS or w <= 0:
                    continue
                correct[k] += w

            je_main = sum(convert_to_main_karat(je_cur_760[k], k) for k in KARATS)
            correct_main = sum(convert_to_main_karat(correct[k], k) for k in KARATS)
            if abs(abs(je_main) - correct_main) < 0.01:
                continue  # not affected

            factor = {}
            for k in KARATS:
                if abs(je_cur_760[k]) > EPS:
                    excess_k = abs(je_cur_760[k]) - correct[k]
                    factor[k] = excess_k / abs(je_cur_760[k])
                else:
                    factor[k] = 0.0

            # All lines of the original JE(s)
            all_lines = (
                JournalEntryLine.query
                .filter(
                    JournalEntryLine.journal_entry_id.in_(je_ids),
                    JournalEntryLine.is_deleted == False,
                )
                .all()
            )

            reversal_lines = []  # (account_id, debit_by_karat dict, credit_by_karat dict)
            acc_760_inv_delta = {k: 0.0 for k in KARATS}

            for l in all_lines:
                rev_debit = {}
                rev_credit = {}
                for k in KARATS:
                    f = factor.get(k, 0.0)
                    if abs(f) < EPS:
                        continue
                    d = getattr(l, f'debit_{k}k') or 0.0
                    c = getattr(l, f'credit_{k}k') or 0.0
                    if d > 0:
                        amt = round(d * f, 6)
                        if abs(amt) > EPS:
                            rev_credit[k] = rev_credit.get(k, 0.0) + amt
                    if c > 0:
                        amt = round(c * f, 6)
                        if abs(amt) > EPS:
                            rev_debit[k] = rev_debit.get(k, 0.0) + amt

                if rev_debit or rev_credit:
                    reversal_lines.append((l.account_id, rev_debit, rev_credit))
                    if l.account_id == acc_inv.id:
                        for k, amt in rev_debit.items():
                            acc_760_inv_delta[k] += amt
                        for k, amt in rev_credit.items():
                            acc_760_inv_delta[k] -= amt

            if not reversal_lines:
                continue

            for k in KARATS:
                acc_760_delta[k] += acc_760_inv_delta[k]

            invoice_rows.append({
                'invoice_id': inv_id,
                'invoice_number': inv.invoice_number,
                'factor': {k: round(factor[k], 6) for k in KARATS if abs(factor.get(k, 0.0)) > EPS},
                'account_760_delta': {k: round(v, 6) for k, v in acc_760_inv_delta.items() if abs(v) > EPS},
                'reversal_lines': [
                    {'account_id': acc_id, 'debit': rd, 'credit': rc}
                    for acc_id, rd, rc in reversal_lines
                ],
            })

            if apply:
                je = JournalEntry(
                    entry_number=_generate_journal_entry_number('JE', je_date),
                    date=je_date,
                    description=(
                        f"تسوية تاريخية - عكس تضخيم وزن فاتورة بيع رقم "
                        f"{inv.invoice_number} ({REF_TYPE})"
                    ),
                    entry_type='عادي',
                    reference_type='invoice',
                    reference_id=inv_id,
                    reference_number=inv.invoice_number,
                    created_by='admin',
                    is_draft=False,
                    is_posted=True,
                    posted_at=je_date,
                    posted_by='admin',
                )
                db.session.add(je)
                db.session.flush()

                line_desc = (
                    f"تسوية تاريخية لتضخيم الوزن - فاتورة {inv.invoice_number} ({REF_TYPE}) "
                    f"بتاريخ {run_dt.date().isoformat()}"
                )
                for acc_id, rd, rc in reversal_lines:
                    jline = JournalEntryLine(
                        journal_entry_id=je.id,
                        account_id=acc_id,
                        description=line_desc,
                    )
                    for k, amt in rd.items():
                        setattr(jline, f'debit_{k}k', amt)
                    for k, amt in rc.items():
                        setattr(jline, f'credit_{k}k', amt)
                    db.session.add(jline)
                    touched_account_ids.add(acc_id)

                if any(abs(v) > EPS for v in acc_760_inv_delta.values()):
                    direction_amounts = {k: v for k, v in acc_760_inv_delta.items() if abs(v) > EPS}
                    # SafeBoxTransaction can only carry one direction; if signs differ across
                    # karats for the same invoice, split into separate rows.
                    pos = {k: v for k, v in direction_amounts.items() if v > 0}
                    neg = {k: -v for k, v in direction_amounts.items() if v < 0}
                    for direction, amounts in (('in', pos), ('out', neg)):
                        if not amounts:
                            continue
                        tx = SafeBoxTransaction(
                            safe_box_id=SAFE_BOX_ID,
                            ref_type=REF_TYPE,
                            ref_id=je.id,
                            invoice_id=inv_id,
                            direction=direction,
                            amount_cash=0.0,
                            weight_18k=round(amounts.get(18, 0.0), 6),
                            weight_21k=round(amounts.get(21, 0.0), 6),
                            weight_22k=round(amounts.get(22, 0.0), 6),
                            weight_24k=round(amounts.get(24, 0.0), 6),
                            notes=line_desc,
                            created_by='admin',
                        )
                        db.session.add(tx)

        print(f"عدد الفواتير المُسوّاة: {len(invoice_rows)}")
        for k in KARATS:
            if abs(acc_760_delta.get(k, 0.0)) > EPS:
                acc_after = round(balance_before[k] + acc_760_delta[k], 6)
                led_after = round(ledger_before[k] + acc_760_delta[k], 6)
                print(f"\n  عيار {k}:")
                print(f"    إجمالي التصحيح (760)          = {acc_760_delta[k]:>14,.3f}")
                print(f"    رصيد حساب 760 قبل             = {balance_before[k]:>14,.3f}")
                print(f"    رصيد حساب 760 بعد             = {acc_after:>14,.3f}")
                print(f"    سند صرف [{SAFE_BOX_ID}] قبل           = {ledger_before[k]:>14,.3f}")
                print(f"    سند صرف [{SAFE_BOX_ID}] بعد           = {led_after:>14,.3f}")

        report = {
            'run_at': run_dt.isoformat(),
            'applied': apply,
            'ref_type': REF_TYPE,
            'safe_box_id': SAFE_BOX_ID,
            'safe_box_name': sb.name,
            'account_inventory_id': acc_inv.id,
            'account_inventory_number': acc_inv.account_number,
            'invoice_count': len(invoice_rows),
            'account_760_balance_before': {k: round(balance_before[k], 6) for k in KARATS},
            'account_760_balance_after': {
                k: round(balance_before[k] + acc_760_delta.get(k, 0.0), 6) for k in KARATS
            },
            'safebox_ledger_before': {k: round(ledger_before[k], 6) for k in KARATS},
            'safebox_ledger_after': {
                k: round(ledger_before[k] + acc_760_delta.get(k, 0.0), 6) for k in KARATS
            },
            'invoices': invoice_rows,
        }

        reports_dir = os.path.join(os.path.dirname(__file__), 'reports')
        os.makedirs(reports_dir, exist_ok=True)
        report_path = os.path.join(
            reports_dir,
            f"sale_invoice_qty_bug_reversal_{run_dt.strftime('%Y%m%dT%H%M%SZ')}"
            f"{'_applied' if apply else '_dryrun'}.json"
        )
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\nتم كتابة التقرير: {report_path}")

        if apply:
            touched_account_ids.add(acc_inv.id)
            _recalculate_account_balances_for_accounts(touched_account_ids)
            db.session.commit()
            print(f"\n✅ تم الحفظ. عدد القيود العكسية المُنشأة: {len(invoice_rows)}")
        else:
            db.session.rollback()
            print("\n(DRY RUN) لتطبيق التغييرات فعليًا أضف --apply")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    run(apply=args.apply)
