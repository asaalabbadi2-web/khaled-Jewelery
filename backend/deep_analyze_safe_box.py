"""
deep_analyze_safe_box.py
==========================
تحليل أعمق لحساب خزينة ذهب معيّنة (بعد أن أصبح سند الصرف = كشف الحساب، لكن
كشف الحساب نفسه قد لا يطابق الكمية الفعلية في الخزينة).

يطبع:
  1. كل قيود الرصيد الافتتاحي (entry_type='افتتاحي') على حساب الخزينة بالتفصيل.
  2. ملخص صافي الوزن (بالعيار الرئيسي) لكل reference_type.
  3. ملخص صافي الوزن لكل (نوع الفاتورة + نوع الذهب) لقيود الفواتير.
  4. أي JournalEntry له أكثر من سطر واحد على نفس حساب الخزينة (احتمال تكرار).

قراءة فقط، لا يُغيّر أي شيء.

تشغيل:
    docker cp backend/deep_analyze_safe_box.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/deep_analyze_safe_box.py --safe-box-id 30
"""

import os
import sys
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, SafeBox, Account, JournalEntry, JournalEntryLine, Invoice
from routes import convert_to_main_karat


def net_main_karat(line):
    total = 0.0
    for k in (18, 21, 22, 24):
        w = (getattr(line, f'debit_{k}k') or 0) - (getattr(line, f'credit_{k}k') or 0)
        total += convert_to_main_karat(w, k)
    return total


def run(safe_box_id: int):
    with app.app_context():
        sb = SafeBox.query.get(safe_box_id)
        acc = Account.query.get(sb.account_id)
        print(f"[{sb.id}] {sb.name}  (account_id={sb.account_id} - {acc.name if acc else '?'})\n")

        lines = (
            JournalEntryLine.query
            .join(JournalEntry)
            .filter(
                JournalEntryLine.account_id == sb.account_id,
                JournalEntry.is_deleted == False,
                JournalEntryLine.is_deleted == False,
                JournalEntry.is_posted == True,
            )
            .all()
        )

        # 1. Opening balance entries
        print("=" * 60)
        print("1) قيود الرصيد الافتتاحي (افتتاحي)")
        print("=" * 60)
        opening_total = 0.0
        for line in lines:
            entry = line.journal_entry
            if getattr(entry, 'entry_type', None) != 'افتتاحي':
                continue
            nmk = net_main_karat(line)
            opening_total += nmk
            print(f"  JE {entry.id} ({getattr(entry,'entry_number',None)}) date={getattr(entry,'date',None)} "
                  f"net_main_karat={nmk:>10,.3f}  "
                  f"w18={(line.debit_18k or 0)-(line.credit_18k or 0):.3f} "
                  f"w21={(line.debit_21k or 0)-(line.credit_21k or 0):.3f} "
                  f"w22={(line.debit_22k or 0)-(line.credit_22k or 0):.3f} "
                  f"w24={(line.debit_24k or 0)-(line.credit_24k or 0):.3f}")
        print(f"\n  إجمالي الرصيد الافتتاحي (عيار رئيسي) = {opening_total:,.3f}\n")

        # 2. Summary by reference_type
        print("=" * 60)
        print("2) صافي الوزن (عيار رئيسي) حسب reference_type")
        print("=" * 60)
        by_ref = defaultdict(lambda: {'count': 0, 'net': 0.0})
        for line in lines:
            entry = line.journal_entry
            rt = (getattr(entry, 'reference_type', None) or '').strip().lower() or '(فارغ/يدوي)'
            nmk = net_main_karat(line)
            by_ref[rt]['count'] += 1
            by_ref[rt]['net'] += nmk
        for rt, info in sorted(by_ref.items(), key=lambda x: -abs(x[1]['net'])):
            print(f"  {rt:25} عدد={info['count']:5}  صافي={info['net']:>12,.3f}")

        # 3. Summary by invoice_type + gold_type for invoice-linked entries
        print("\n" + "=" * 60)
        print("3) صافي الوزن حسب (نوع الفاتورة + نوع الذهب) لقيود الفواتير")
        print("=" * 60)
        # Need to map JE -> invoice. Try reference_id on JE, or SafeBoxTransaction.invoice_id won't help here.
        by_inv = defaultdict(lambda: {'count': 0, 'net': 0.0})
        for line in lines:
            entry = line.journal_entry
            rt = (getattr(entry, 'reference_type', None) or '').strip().lower()
            if rt != 'invoice':
                continue
            ref_id = getattr(entry, 'reference_id', None)
            inv = Invoice.query.get(ref_id) if ref_id else None
            key = (
                getattr(inv, 'invoice_type', None) if inv else None,
                (getattr(inv, 'gold_type', None) if inv else None) or 'new',
            )
            nmk = net_main_karat(line)
            by_inv[key]['count'] += 1
            by_inv[key]['net'] += nmk
        for key, info in sorted(by_inv.items(), key=lambda x: -abs(x[1]['net'])):
            print(f"  invoice_type={str(key[0]):20} gold_type={str(key[1]):10} عدد={info['count']:5}  صافي={info['net']:>12,.3f}")

        # 4. JEs with multiple lines on this account (possible duplicates)
        print("\n" + "=" * 60)
        print("4) قيود لها أكثر من سطر واحد على حساب هذه الخزينة")
        print("=" * 60)
        by_je = defaultdict(list)
        for line in lines:
            by_je[line.journal_entry_id].append(line)
        dup_total = 0.0
        for je_id, ls in by_je.items():
            if len(ls) <= 1:
                continue
            entry = ls[0].journal_entry
            nmk = sum(net_main_karat(l) for l in ls)
            dup_total += nmk
            rt = (getattr(entry, 'reference_type', None) or '').strip().lower() or '(فارغ/يدوي)'
            print(f"  JE {je_id} ({getattr(entry,'entry_number',None)}, {rt}): {len(ls)} أسطر, صافي={nmk:>10,.3f}")
        print(f"\n  إجمالي القيود متعددة الأسطر = {dup_total:,.3f}")

        # Grand total check
        grand_total = sum(net_main_karat(l) for l in lines)
        print(f"\nالإجمالي العام لكل الأسطر (يجب أن يطابق كشف الحساب) = {grand_total:,.3f}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--safe-box-id', type=int, required=True)
    args = parser.parse_args()
    run(args.safe_box_id)
