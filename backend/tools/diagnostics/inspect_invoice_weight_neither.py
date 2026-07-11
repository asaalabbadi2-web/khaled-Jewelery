"""
inspect_invoice_weight_neither.py
====================================
يطبع التفاصيل الكاملة (كل أصناف الفاتورة + أسطر JE) للفواتير التي لم
تطابق "matches_neither" في inspect_invoice_weight_vs_qty.py، لمعرفة نمط
الخطأ فيها.

قراءة فقط.

تشغيل:
    docker cp backend/inspect_invoice_weight_neither.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/inspect_invoice_weight_neither.py --account-id 760
"""

import os
import sys
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, JournalEntry, JournalEntryLine, Invoice, InvoiceItem
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

        shown = 0
        total_excess_over_noqty = 0.0
        neither_count = 0

        for inv_id, je_lines in je_by_inv.items():
            inv = Invoice.query.get(inv_id) if inv_id else None
            if not inv:
                continue
            if getattr(inv, 'invoice_type', None) != 'بيع' or (getattr(inv, 'gold_type', None) or 'new') != 'new':
                continue

            je_net = sum(net_main_karat_line(l) for l in je_lines)
            je_abs = abs(je_net)

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

            d_noqty = abs(je_abs - w_noqty)
            d_qty = abs(je_abs - w_qty)
            if d_noqty < 0.01 and d_noqty <= d_qty:
                continue
            if d_qty < 0.01:
                continue

            neither_count += 1
            total_excess_over_noqty += (je_abs - w_noqty)

            if shown < 15:
                shown += 1
                print(f"\ninvoice_id={inv_id} ({inv.invoice_number}) JE_net={je_net:.3f} (abs={je_abs:.3f}) "
                      f"W_noqty={w_noqty:.3f} W_qty={w_qty:.3f}")
                for l in je_lines:
                    print(f"   JE line: net={net_main_karat_line(l):.3f} "
                          f"w18={(l.debit_18k or 0)-(l.credit_18k or 0):.3f} "
                          f"w21={(l.debit_21k or 0)-(l.credit_21k or 0):.3f} "
                          f"w22={(l.debit_22k or 0)-(l.credit_22k or 0):.3f} "
                          f"w24={(l.debit_24k or 0)-(l.credit_24k or 0):.3f}")
                for it in items:
                    print(f"   item: name={it.name!r} qty={it.quantity} karat={it.karat} weight={it.weight} "
                          f"standing_weight={it.standing_weight} stones_weight={it.stones_weight}")

        print(f"\n\nإجمالي: عدد={neither_count}  الفرق الإجمالي (JE_abs - W_noqty) = {total_excess_over_noqty:,.3f}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--account-id', type=int, required=True)
    args = parser.parse_args()
    run(account_id=args.account_id)
