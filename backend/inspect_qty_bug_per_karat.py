"""
inspect_qty_bug_per_karat.py
==============================
يحسب توزيع "فرق التضخيم" (مشكلة الوزن×الكمية في فواتير بيع/new التاريخية
على حساب 760) لكل عيار على حدة (18/21/22/24)، بدل تحويله إلى عيار رئيسي
واحد.

لكل فاتورة "بيع"/new تحتوي أسطر JE على حساب 760:
  - للك عيار k: je_cur_k = sum(debit_k - credit_k) عبر أسطر القيد (سالب لأنه بيع)
  - correct_k  = -sum(InvoiceItem.weight لهذا العيار، بدون ضرب بالكمية)
  - excess_k   = |je_cur_k| - |correct_k|   (الفرق الموجب = مقدار التضخيم)

تُجمع excess_k لكل العيارات عبر كل الفواتير المتأثرة (التي |je_abs - w_noqty| > 0.01)
وتُطبع كملخص نهائي: المبلغ الذي يجب "إعادته" لحساب 760 ولـ SBT[30] لكل عيار،
دون لمس القيود التاريخية لأي فاتورة.

قراءة فقط.

تشغيل:
    docker cp backend/inspect_qty_bug_per_karat.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/inspect_qty_bug_per_karat.py --account-id 760
"""

import os
import sys
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, JournalEntry, JournalEntryLine, Invoice, InvoiceItem


KARATS = (18, 21, 22, 24)


def run(account_id: int):
    with app.app_context():
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
        affected_count = 0
        affected_invoices = []

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

            # هل هذه الفاتورة من ضمن الفواتير المتأثرة؟ (مقارنة بالإجمالي بالعيار الرئيسي تمت سابقاً)
            from routes import convert_to_main_karat
            je_abs_total = sum(abs(je_cur[k]) for k in KARATS)
            correct_total = sum(correct[k] for k in KARATS)
            # تقريب: نعتمد على فرق الإجمالي (غير محول) لتحديد إن كانت متأثرة
            je_main = sum(convert_to_main_karat(je_cur[k], k) for k in KARATS)
            correct_main = sum(convert_to_main_karat(correct[k], k) for k in KARATS)
            if abs(abs(je_main) - correct_main) < 0.01:
                continue  # غير متأثرة

            affected_count += 1
            affected_invoices.append(inv.invoice_number)

            for k in KARATS:
                excess_k = abs(je_cur[k]) - correct[k]
                if abs(excess_k) > 1e-9:
                    excess_by_karat[k] += excess_k

        print("=" * 60)
        print(f"عدد الفواتير المتأثرة: {affected_count}")
        print("=" * 60)
        print("\nالفرق (excess) لكل عيار - المبلغ الذي يجب 'إعادته' لحساب 760 و SBT[30]:")
        total = 0.0
        for k in KARATS:
            v = excess_by_karat.get(k, 0.0)
            total += v
            print(f"  عيار {k}: {v:>14,.3f} جم")
        print(f"\nالإجمالي (غير محول لعيار رئيسي): {total:,.3f} جم")

        from routes import convert_to_main_karat
        total_main = sum(convert_to_main_karat(excess_by_karat.get(k, 0.0), k) for k in KARATS)
        print(f"الإجمالي محولاً للعيار الرئيسي (21): {total_main:,.3f} جم")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--account-id', type=int, required=True)
    args = parser.parse_args()
    run(account_id=args.account_id)
