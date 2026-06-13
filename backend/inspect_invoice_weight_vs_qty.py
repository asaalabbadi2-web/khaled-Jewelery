"""
inspect_invoice_weight_vs_qty.py
==================================
يفحص فواتير "بيع" (ذهب جديد) المؤثرة على حساب 760: هل صافي القيد (JE)
يطابق "وزن السطر" (InvoiceItem.weight) كما هو، أم يطابق "الوزن × الكمية"
(weight * quantity)؟

الفرضية: قد تكون بعض القيود القديمة محسوبة بضرب الوزن في الكمية (مشكلة
عُرفت وأُصلحت سابقاً في تقرير الربح بالجرام - commit e91790f)، مما يُضخّم
صافي حساب 760 مقارنة بالوزن الفعلي للأصناف.

لكل فاتورة "بيع"/new تطبع:
  - JE_net   : صافي القيد على حساب 760 (عيار رئيسي)
  - W_noqty  : sum(item.weight بالعيار الرئيسي)  — بدون ضرب بالكمية
  - W_qty    : sum(item.weight * item.quantity بالعيار الرئيسي) — مع الضرب
  - أقرب أيهما لـ JE_net (noqty / qty / neither)

ثم ملخص: عدد الفواتير في كل فئة + إجمالي الفرق المحتمل (W_qty - W_noqty)
لمعرفة حجم "التضخيم" الإجمالي إن وُجد.

قراءة فقط.

تشغيل:
    docker cp backend/inspect_invoice_weight_vs_qty.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/inspect_invoice_weight_vs_qty.py --account-id 760
"""

import os
import sys
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, Account, JournalEntry, JournalEntryLine, Invoice, InvoiceItem
from routes import convert_to_main_karat


def net_main_karat_line(line):
    total = 0.0
    for k in (18, 21, 22, 24):
        w = (getattr(line, f'debit_{k}k') or 0) - (getattr(line, f'credit_{k}k') or 0)
        total += convert_to_main_karat(w, k)
    return total


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

        cat_counts = defaultdict(int)
        cat_je_sum = defaultdict(float)
        cat_noqty_sum = defaultdict(float)
        cat_qty_sum = defaultdict(float)

        examples = defaultdict(list)

        for inv_id, je_lines in je_by_inv.items():
            inv = Invoice.query.get(inv_id) if inv_id else None
            if not inv:
                continue
            inv_type = getattr(inv, 'invoice_type', None)
            gold_type = (getattr(inv, 'gold_type', None) or 'new')
            if inv_type != 'بيع' or gold_type != 'new':
                continue

            je_net = sum(net_main_karat_line(l) for l in je_lines)

            items = InvoiceItem.query.filter_by(invoice_id=inv_id).all()
            w_noqty = 0.0
            w_qty = 0.0
            for it in items:
                k = float(it.karat or 0)
                w = float(it.weight or 0)
                q = float(it.quantity or 1)
                if k <= 0 or w <= 0:
                    continue
                mk = convert_to_main_karat(w, int(round(k)))
                w_noqty += mk
                w_qty += mk * q

            # JE for بيع is negative (credit/out); compare magnitudes
            je_abs = abs(je_net)
            d_noqty = abs(je_abs - w_noqty)
            d_qty = abs(je_abs - w_qty)

            if d_noqty < 0.01 and d_noqty <= d_qty:
                cat = 'matches_noqty'
            elif d_qty < 0.01:
                cat = 'matches_qty'
            else:
                cat = 'matches_neither'

            cat_counts[cat] += 1
            cat_je_sum[cat] += je_abs
            cat_noqty_sum[cat] += w_noqty
            cat_qty_sum[cat] += w_qty

            if cat != 'matches_noqty' and len(examples[cat]) < 5:
                examples[cat].append((inv_id, getattr(inv, 'invoice_number', None), je_net, w_noqty, w_qty))

        print("=" * 70)
        print("مقارنة JE_net (حساب 760) مع وزن الأصناف (بدون/مع ضرب الكمية) - فواتير بيع/new")
        print("=" * 70)
        for cat in ('matches_noqty', 'matches_qty', 'matches_neither'):
            print(f"\n  {cat}: عدد={cat_counts[cat]}")
            print(f"      sum(JE_abs)   = {cat_je_sum[cat]:>12,.3f}")
            print(f"      sum(W_noqty)  = {cat_noqty_sum[cat]:>12,.3f}")
            print(f"      sum(W_qty)    = {cat_qty_sum[cat]:>12,.3f}")
            for ex in examples[cat]:
                print(f"      مثال: invoice_id={ex[0]} ({ex[1]}) JE_net={ex[2]:.3f} W_noqty={ex[3]:.3f} W_qty={ex[4]:.3f}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--account-id', type=int, required=True)
    args = parser.parse_args()
    run(account_id=args.account_id)
