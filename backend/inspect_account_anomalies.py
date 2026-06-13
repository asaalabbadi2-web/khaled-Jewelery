"""
inspect_account_anomalies.py
==============================
متابعة لـ deep_analyze_safe_box.py لخزينة [30] (account_id يُمرَّر كوسيط).

يطبع بالتفصيل:
  1. كل قيود (فارغ/يدوي) غير الافتتاحية على الحساب (reference_type فارغ
     و entry_type != 'افتتاحي') — لمعرفة ما تمثله الـ -2,514.10 المتبقية.
  2. لعيّنة من القيود متعددة الأسطر على الحساب (الأكبر بالقيمة المطلقة،
     وأيضًا أمثلة من كل invoice_type) — كل أسطر القيد كاملة + معلومات
     الفاتورة المرتبطة (النوع، نوع الذهب، الوزن الإجمالي/وزن الفصوص إن وُجد).

قراءة فقط.

تشغيل:
    docker cp backend/inspect_account_anomalies.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/inspect_account_anomalies.py --account-id 760
"""

import os
import sys
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, Account, JournalEntry, JournalEntryLine, Invoice
from routes import convert_to_main_karat


def net_main_karat(line):
    total = 0.0
    for k in (18, 21, 22, 24):
        w = (getattr(line, f'debit_{k}k') or 0) - (getattr(line, f'credit_{k}k') or 0)
        total += convert_to_main_karat(w, k)
    return total


def fmt_line(line):
    return (
        f"w18={(line.debit_18k or 0)-(line.credit_18k or 0):.3f} "
        f"w21={(line.debit_21k or 0)-(line.credit_21k or 0):.3f} "
        f"w22={(line.debit_22k or 0)-(line.credit_22k or 0):.3f} "
        f"w24={(line.debit_24k or 0)-(line.credit_24k or 0):.3f} "
        f"cash_debit={line.cash_debit or 0:.2f} cash_credit={line.cash_credit or 0:.2f}"
    )


def run(account_id: int):
    with app.app_context():
        acc = Account.query.get(account_id)
        print(f"حساب [{account_id}] {acc.name if acc else '?'}\n")

        lines = (
            JournalEntryLine.query
            .join(JournalEntry)
            .filter(
                JournalEntryLine.account_id == account_id,
                JournalEntry.is_deleted == False,
                JournalEntryLine.is_deleted == False,
                JournalEntry.is_posted == True,
            )
            .all()
        )

        # 1. Non-opening manual entries (reference_type empty, entry_type != 'افتتاحي')
        print("=" * 60)
        print("1) قيود (فارغ/يدوي) غير افتتاحية")
        print("=" * 60)
        for line in lines:
            entry = line.journal_entry
            rt = (getattr(entry, 'reference_type', None) or '').strip().lower()
            et = getattr(entry, 'entry_type', None)
            if rt or et == 'افتتاحي':
                continue
            nmk = net_main_karat(line)
            print(f"  JE {entry.id} ({getattr(entry,'entry_number',None)}) date={getattr(entry,'date',None)} "
                  f"entry_type={et!r} description={getattr(entry,'description',None)!r} "
                  f"created_by={getattr(entry,'created_by',None)!r}")
            print(f"      net_main_karat={nmk:>10,.3f}  {fmt_line(line)}")

            # Print ALL lines of this JE (across all accounts) for context
            all_lines = [l for l in (entry.lines or []) if not getattr(l, 'is_deleted', False)]
            for ol in all_lines:
                oacc = Account.query.get(ol.account_id)
                print(f"        - account[{ol.account_id}] {oacc.name if oacc else '?'}: {fmt_line(ol)}")
            print()

        # 2. Multi-line JEs - sample
        print("\n" + "=" * 60)
        print("2) عيّنة من القيود متعددة الأسطر (الأكبر صافيًا)")
        print("=" * 60)
        by_je = defaultdict(list)
        for line in lines:
            by_je[line.journal_entry_id].append(line)

        multi = []
        for je_id, ls in by_je.items():
            if len(ls) <= 1:
                continue
            nmk = sum(net_main_karat(l) for l in ls)
            multi.append((je_id, ls, nmk))

        multi.sort(key=lambda x: -abs(x[2]))

        for je_id, ls, nmk in multi[:8]:
            entry = ls[0].journal_entry
            rt = (getattr(entry, 'reference_type', None) or '').strip().lower()
            print(f"\n  JE {je_id} ({getattr(entry,'entry_number',None)}) date={getattr(entry,'date',None)} "
                  f"reference_type={rt!r} reference_id={getattr(entry,'reference_id',None)} "
                  f"description={getattr(entry,'description',None)!r}")
            for l in ls:
                print(f"      [account {account_id}] net={net_main_karat(l):>10,.3f}  {fmt_line(l)}")

            if rt == 'invoice':
                inv = Invoice.query.get(getattr(entry, 'reference_id', None))
                if inv:
                    print(f"      فاتورة #{inv.invoice_number} invoice_type={inv.invoice_type!r} "
                          f"gold_type={getattr(inv,'gold_type',None)!r}")
                    # Print item-level weight fields if present
                    for item in (getattr(inv, 'items', None) or []):
                        attrs = {k: v for k, v in vars(item).items()
                                 if not k.startswith('_') and ('weight' in k or 'stone' in k or 'فص' in k)}
                        if attrs:
                            print(f"        item: {attrs}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--account-id', type=int, required=True)
    args = parser.parse_args()
    run(args.account_id)
