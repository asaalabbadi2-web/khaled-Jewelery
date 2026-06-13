"""
inspect_invoice_gold_routing_v2.py
=====================================
نسخة مُصححة من inspect_invoice_gold_routing.py: تجمع أولًا كل أسطر JE على
حساب 760 لكل فاتورة (invoice_id) كمجموعة واحدة (لتفادي ازدواج العد عند
الفواتير التي لها أكثر من سطر على هذا الحساب)، ثم تقارن:

  - JE_net   : صافي وزن (عيار رئيسي) لكل أسطر القيد على حساب 760 لهذه الفاتورة.
  - SBT_net  : صافي وزن (عيار رئيسي، من weight_Xk فقط) لكل صفوف
               SafeBoxTransaction المرتبطة بهذه الفاتورة على safe_box [30].
  - SBT_net_other: نفس الشيء لكل الخزائن الأخرى.

يطبع ملخصًا حسب (invoice_type, gold_type) لـ: عدد الفواتير، صافي JE،
صافي SBT[30]، صافي SBT (خزائن أخرى)، وعدد الفواتير التي JE_net != SBT_net(30).

قراءة فقط.

تشغيل:
    docker cp backend/inspect_invoice_gold_routing_v2.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/inspect_invoice_gold_routing_v2.py --account-id 760 --safe-box-id 30
"""

import os
import sys
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, Account, SafeBox, JournalEntry, JournalEntryLine, Invoice, SafeBoxTransaction
from routes import convert_to_main_karat


def net_main_karat_line(line):
    total = 0.0
    for k in (18, 21, 22, 24):
        w = (getattr(line, f'debit_{k}k') or 0) - (getattr(line, f'credit_{k}k') or 0)
        total += convert_to_main_karat(w, k)
    return total


def sbt_net_main_karat(tx):
    total = 0.0
    for k in (18, 21, 22, 24):
        w = getattr(tx, f'weight_{k}k') or 0.0
        if tx.direction == 'out':
            w = -w
        total += convert_to_main_karat(w, k)
    return total


def run(account_id: int, safe_box_id: int):
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

        # Group JE lines by invoice_id
        je_by_inv = defaultdict(list)
        for line in lines:
            entry = line.journal_entry
            inv_id = getattr(entry, 'reference_id', None)
            je_by_inv[inv_id].append(line)

        # Pre-fetch all SBT rows for these invoices, grouped by invoice_id
        inv_ids = list(je_by_inv.keys())
        sbt_by_inv = defaultdict(list)
        for tx in SafeBoxTransaction.query.filter(SafeBoxTransaction.invoice_id.in_(inv_ids)).all():
            sbt_by_inv[tx.invoice_id].append(tx)

        summary = defaultdict(lambda: {
            'count': 0, 'je_net': 0.0, 'sbt30_net': 0.0, 'sbt_other_net': 0.0,
            'mismatch_count': 0, 'mismatch_sum': 0.0,
        })

        for inv_id, je_lines in je_by_inv.items():
            inv = Invoice.query.get(inv_id) if inv_id else None
            inv_type = getattr(inv, 'invoice_type', None) if inv else None
            gold_type = (getattr(inv, 'gold_type', None) if inv else None) or 'new'
            key = (inv_type, gold_type)

            je_net = sum(net_main_karat_line(l) for l in je_lines)

            sbt30_net = 0.0
            sbt_other_net = 0.0
            for tx in sbt_by_inv.get(inv_id, []):
                nmk = sbt_net_main_karat(tx)
                if tx.safe_box_id == safe_box_id:
                    sbt30_net += nmk
                else:
                    sbt_other_net += nmk

            info = summary[key]
            info['count'] += 1
            info['je_net'] += je_net
            info['sbt30_net'] += sbt30_net
            info['sbt_other_net'] += sbt_other_net

            diff = round(je_net - sbt30_net, 3)
            if abs(diff) > 0.001:
                info['mismatch_count'] += 1
                info['mismatch_sum'] += diff

        print("=" * 70)
        print(f"مقارنة لكل فاتورة: صافي JE على حساب {account_id}  مقابل  صافي SBT على safe_box [{safe_box_id}]")
        print("=" * 70)
        grand_je = 0.0
        grand_sbt30 = 0.0
        for key, info in sorted(summary.items(), key=lambda x: -abs(x[1]['je_net'])):
            grand_je += info['je_net']
            grand_sbt30 += info['sbt30_net']
            print(f"\n  invoice_type={str(key[0]):20} gold_type={str(key[1]):8} عدد={info['count']:5}")
            print(f"      JE_net(760)        = {info['je_net']:>12,.3f}")
            print(f"      SBT_net([{safe_box_id}])     = {info['sbt30_net']:>12,.3f}")
            print(f"      SBT_net(غيرها)      = {info['sbt_other_net']:>12,.3f}")
            print(f"      فواتير JE != SBT[{safe_box_id}]: عدد={info['mismatch_count']:5}  صافي الفرق={info['mismatch_sum']:>12,.3f}")

        print(f"\nالإجمالي العام:")
        print(f"  JE_net(760)    = {grand_je:,.3f}")
        print(f"  SBT_net([{safe_box_id}]) = {grand_sbt30:,.3f}")
        print(f"  الفرق (JE - SBT) = {grand_je - grand_sbt30:,.3f}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--account-id', type=int, required=True)
    parser.add_argument('--safe-box-id', type=int, required=True)
    args = parser.parse_args()
    run(args.account_id, args.safe_box_id)
