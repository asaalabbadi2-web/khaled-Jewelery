"""
check_opening_balances_vs_gap.py
==================================
يفحص قيود الرصيد الافتتاحي (entry_type='افتتاحي') المؤثرة على حسابات خزائن
الذهب، ويقارن صافي وزنها (بالعيار الرئيسي) مع فرق "كشف الحساب - سند الصرف"
المحسوب من diagnose_safe_box_ledger_mismatch.py، لمعرفة هل الفرق ناتج عن
رصيد افتتاحي لم يُنشأ له SafeBoxTransaction (باستثناء بالتصميم).

قراءة فقط، لا يُغيّر أي شيء.

تشغيل:
    docker cp backend/check_opening_balances_vs_gap.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/check_opening_balances_vs_gap.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from sqlalchemy import func
from models import db, Account, SafeBox, SafeBoxTransaction, JournalEntry, JournalEntryLine
from routes import _account_weight_balance_main_karat, convert_to_main_karat


KARATS = ['18k', '21k', '22k', '24k']


def ledger_balance_weight(safe_box_id: int):
    q = SafeBoxTransaction.query.filter_by(safe_box_id=safe_box_id)

    def _sum(field, direction):
        col = getattr(SafeBoxTransaction, field)
        return float(
            q.with_entities(func.coalesce(func.sum(col), 0.0))
            .filter(SafeBoxTransaction.direction == direction)
            .scalar() or 0.0
        )

    weight_main_karat = 0.0
    for k in KARATS:
        karat_num = int(k[:-1])
        w = _sum(f'weight_{k}', 'in') - _sum(f'weight_{k}', 'out')
        weight_main_karat += convert_to_main_karat(w, karat_num)
    return round(weight_main_karat, 6)


def run():
    with app.app_context():
        safe_boxes = [sb for sb in SafeBox.query.filter_by(safe_type='gold', is_active=True).all() if sb.account_id]

        for sb in safe_boxes:
            acc = Account.query.get(sb.account_id)
            if not acc:
                continue
            stmt_weight = _account_weight_balance_main_karat(acc)
            led_weight = ledger_balance_weight(sb.id)
            diff_weight = round(stmt_weight - led_weight, 6)

            opening_lines = (
                JournalEntryLine.query
                .join(JournalEntry)
                .filter(
                    JournalEntryLine.account_id == sb.account_id,
                    JournalEntry.entry_type == 'افتتاحي',
                    JournalEntry.is_deleted == False,
                    JournalEntryLine.is_deleted == False,
                )
                .all()
            )

            opening_net = 0.0
            for line in opening_lines:
                for k in (18, 21, 22, 24):
                    w = (getattr(line, f'debit_{k}k') or 0) - (getattr(line, f'credit_{k}k') or 0)
                    opening_net += convert_to_main_karat(w, k)

            if abs(diff_weight) < 0.0005 and abs(opening_net) < 0.0005:
                continue

            match = "✅ يطابق الفرق" if abs(diff_weight - opening_net) < 0.001 else "❌ لا يطابق"
            print(f"[{sb.id:3}] {sb.name}")
            print(f"      الفرق (كشف الحساب - سند الصرف) = {diff_weight:>10,.3f}")
            print(f"      صافي قيود الرصيد الافتتاحي     = {opening_net:>10,.3f}  ({len(opening_lines)} قيد)  {match}")
            print()


if __name__ == '__main__':
    run()
