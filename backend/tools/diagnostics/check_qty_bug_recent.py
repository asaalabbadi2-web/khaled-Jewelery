"""
check_qty_bug_recent.py
=========================
يفحص: هل مشكلة "القيد = الوزن × الكمية" (أو أي تضخيم آخر) في فواتير
"بيع"/ذهب جديد لا تزال تحدث في الفواتير الحديثة، أم توقفت؟

يطبع لكل فاتورة بيع/new (مرتبة بالتاريخ تنازليًا، آخر 30 فاتورة):
  invoice_number, date, JE_net(760), W_noqty(الأصناف), هل تطابق؟

قراءة فقط.

تشغيل:
    docker cp backend/check_qty_bug_recent.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/check_qty_bug_recent.py --account-id 760
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
            je_by_inv[inv_id].append((line, entry))

        rows = []
        for inv_id, je_lines in je_by_inv.items():
            inv = Invoice.query.get(inv_id) if inv_id else None
            if not inv:
                continue
            if getattr(inv, 'invoice_type', None) != 'بيع' or (getattr(inv, 'gold_type', None) or 'new') != 'new':
                continue

            je_net = sum(net_main_karat_line(l) for l, _ in je_lines)
            je_abs = abs(je_net)
            date = je_lines[0][1].date

            items = InvoiceItem.query.filter_by(invoice_id=inv_id).all()
            w_noqty = 0.0
            for it in items:
                k = float(it.karat or 0)
                w = float(it.weight or 0)
                if k <= 0 or w <= 0:
                    continue
                w_noqty += convert_to_main_karat(w, int(round(k)))

            rows.append((date, inv.invoice_number, je_abs, w_noqty))

        rows.sort(key=lambda r: r[0], reverse=True)
        print(f"{'date':25} {'invoice':15} {'JE_abs':>10} {'W_noqty':>10} {'match?'}")
        for date, num, je_abs, w_noqty in rows[:30]:
            match = 'OK' if abs(je_abs - w_noqty) < 0.01 else 'MISMATCH'
            print(f"{str(date):25} {num:15} {je_abs:>10.3f} {w_noqty:>10.3f} {match}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--account-id', type=int, required=True)
    args = parser.parse_args()
    run(account_id=args.account_id)
