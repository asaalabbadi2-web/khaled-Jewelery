"""
inspect_invoice_gold_routing.py
=================================
يفحص: لقيود الفواتير (بيع/شراء، ذهب جديد) المؤثرة على حساب 760
("مخزون الذهب المعروض للبيع وزني")، هل توجد حركة SafeBoxTransaction
مقابلة، وعلى أي safe_box_id؟

أيضًا يطبع قيم إعدادات التوجيه: sale_gold_safe_box_id,
main_scrap_gold_safe_box_id.

الهدف: معرفة هل حساب 760 يمثل فعليًا خزينة [30] فقط، أم أنه حساب
محاسبي مُجمَّع تتوزع حركاته الفعلية (SBT) على خزائن مختلفة (أو لا تُسجَّل
في SBT أصلاً، كحال الشراء).

قراءة فقط.

تشغيل:
    docker cp backend/inspect_invoice_gold_routing.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/inspect_invoice_gold_routing.py --account-id 760
"""

import os
import sys
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, Account, SafeBox, Settings, JournalEntry, JournalEntryLine, Invoice, SafeBoxTransaction
from routes import convert_to_main_karat


def net_main_karat(line):
    total = 0.0
    for k in (18, 21, 22, 24):
        w = (getattr(line, f'debit_{k}k') or 0) - (getattr(line, f'credit_{k}k') or 0)
        total += convert_to_main_karat(w, k)
    return total


def run(account_id: int):
    with app.app_context():
        settings_row = Settings.query.first()
        sale_sb_id = getattr(settings_row, 'sale_gold_safe_box_id', None) if settings_row else None
        scrap_sb_id = getattr(settings_row, 'main_scrap_gold_safe_box_id', None) if settings_row else None

        sale_sb = SafeBox.query.get(sale_sb_id) if sale_sb_id else None
        scrap_sb = SafeBox.query.get(scrap_sb_id) if scrap_sb_id else None

        print("=" * 60)
        print("إعدادات توجيه خزائن الذهب")
        print("=" * 60)
        print(f"  sale_gold_safe_box_id       = {sale_sb_id}  -> {sale_sb.name if sale_sb else '(غير محدد)'}")
        print(f"  main_scrap_gold_safe_box_id = {scrap_sb_id} -> {scrap_sb.name if scrap_sb else '(غير محدد)'}")

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

        # group by invoice_type + gold_type, and check SBT existence/location
        summary = defaultdict(lambda: {'count': 0, 'net': 0.0, 'sbt_safe_ids': defaultdict(float), 'no_sbt_net': 0.0, 'no_sbt_count': 0})

        for line in lines:
            entry = line.journal_entry
            inv = Invoice.query.get(getattr(entry, 'reference_id', None))
            inv_type = getattr(inv, 'invoice_type', None) if inv else None
            gold_type = (getattr(inv, 'gold_type', None) if inv else None) or 'new'
            key = (inv_type, gold_type)
            nmk = net_main_karat(line)
            summary[key]['count'] += 1
            summary[key]['net'] += nmk

            # Any SBT rows for this invoice (any ref_type, any safe box)?
            sbt_rows = SafeBoxTransaction.query.filter_by(invoice_id=inv.id).all() if inv else []
            if sbt_rows:
                for r in sbt_rows:
                    w = 0.0
                    for k in (18, 21, 22, 24):
                        w += convert_to_main_karat(
                            (getattr(r, f'weight_{k}k') or 0) * (1 if r.direction == 'in' else -1), k
                        )
                    summary[key]['sbt_safe_ids'][r.safe_box_id] += w
            else:
                summary[key]['no_sbt_net'] += nmk
                summary[key]['no_sbt_count'] += 1

        print("\n" + "=" * 60)
        print("ملخص حسب (نوع الفاتورة + نوع الذهب)")
        print("=" * 60)
        for key, info in sorted(summary.items(), key=lambda x: -abs(x[1]['net'])):
            print(f"\n  invoice_type={str(key[0]):15} gold_type={str(key[1]):8} "
                  f"عدد={info['count']:5}  صافي على حساب 760 ={info['net']:>12,.3f}")
            print(f"      بلا SBT على الإطلاق: عدد={info['no_sbt_count']:5}  صافي={info['no_sbt_net']:>12,.3f}")
            for sb_id, w in info['sbt_safe_ids'].items():
                sb = SafeBox.query.get(sb_id) if sb_id else None
                print(f"      SBT على safe_box[{sb_id}] {sb.name if sb else '?'}: صافي(عيار رئيسي)={w:>12,.3f}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--account-id', type=int, required=True)
    args = parser.parse_args()
    run(args.account_id)
