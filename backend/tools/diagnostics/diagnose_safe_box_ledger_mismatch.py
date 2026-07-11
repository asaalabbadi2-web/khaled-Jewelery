"""
diagnose_safe_box_ledger_mismatch.py
=====================================
يقارن رصيد كل خزينة كما يظهر في كشف الحساب (Account.balance_cash/balance_*k،
المُصحَّح في commit 387ca7b) مع رصيدها في سجل SafeBoxTransaction (المصدر
المستخدم في سند الصرف وبطاقة الخزنة عبر /safe-boxes/balances).

عند وجود فرق، يطبع القيود المحاسبية (JournalEntryLine) المؤثرة على حساب
الخزينة مع نوع كل قيد (reference_type) لمعرفة أي القيود لم تُولِّد حركة
SafeBoxTransaction (القيود اليدوية لا تُولِّد حركة بالتصميم — انظر
_rebuild_safe_box_transactions_for_journal_entry في routes.py).

تشغيل (قراءة فقط، لا يُغيّر أي شيء):
    docker cp backend/diagnose_safe_box_ledger_mismatch.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/diagnose_safe_box_ledger_mismatch.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from sqlalchemy import func
from models import db, Account, SafeBox, SafeBoxTransaction, JournalEntry, JournalEntryLine
from routes import _account_weight_balance_main_karat, convert_to_main_karat


KARATS = ['18k', '21k', '22k', '24k']


def ledger_balance(safe_box_id: int):
    q = SafeBoxTransaction.query.filter_by(safe_box_id=safe_box_id)

    def _sum(field, direction):
        col = getattr(SafeBoxTransaction, field)
        return float(
            q.with_entities(func.coalesce(func.sum(col), 0.0))
            .filter(SafeBoxTransaction.direction == direction)
            .scalar() or 0.0
        )

    cash = _sum('amount_cash', 'in') - _sum('amount_cash', 'out')
    weight_main_karat = 0.0
    for k in KARATS:
        karat_num = int(k[:-1])
        w = _sum(f'weight_{k}', 'in') - _sum(f'weight_{k}', 'out')
        weight_main_karat += convert_to_main_karat(w, karat_num)
    return round(cash, 2), round(weight_main_karat, 6)


def run():
    with app.app_context():
        safe_boxes = [sb for sb in SafeBox.query.all() if sb.account_id]
        print("مقارنة: رصيد كشف الحساب (الصحيح) <-> رصيد سجل SafeBoxTransaction (المستخدم في سند الصرف/بطاقة الخزنة)\n")

        for sb in safe_boxes:
            acc = Account.query.get(sb.account_id)
            if not acc:
                continue
            stmt_cash = round(acc.balance_cash or 0.0, 2)
            stmt_weight = _account_weight_balance_main_karat(acc)
            led_cash, led_weight = ledger_balance(sb.id)

            diff_cash = round(stmt_cash - led_cash, 2)
            diff_weight = round(stmt_weight - led_weight, 6)

            if abs(diff_cash) < 0.005 and abs(diff_weight) < 0.0005:
                continue

            print(f"[{sb.id:3}] {sb.name}")
            print(f"      كشف الحساب: نقدي={stmt_cash:>14,.2f}  وزن={stmt_weight:>10,.3f}")
            print(f"      سند الصرف : نقدي={led_cash:>14,.2f}  وزن={led_weight:>10,.3f}")
            print(f"      الفرق     : نقدي={diff_cash:>14,.2f}  وزن={diff_weight:>10,.3f}")

            # Dump journal entry lines affecting this account, grouped by reference_type
            lines = (
                JournalEntryLine.query
                .join(JournalEntry)
                .filter(
                    JournalEntryLine.account_id == sb.account_id,
                    JournalEntry.is_deleted == False,
                    JournalEntryLine.is_deleted == False,
                )
                .all()
            )
            by_ref = {}
            for line in lines:
                entry = line.journal_entry
                rt = (getattr(entry, 'reference_type', None) or '').strip().lower() or '(فارغ/يدوي)'
                if rt not in by_ref:
                    by_ref[rt] = {'count': 0, 'cash': 0.0}
                by_ref[rt]['count'] += 1
                by_ref[rt]['cash'] += (line.cash_debit or 0) - (line.cash_credit or 0)

            print("      أنواع القيود المؤثرة على حساب الخزينة:")
            for rt, info in sorted(by_ref.items()):
                print(f"        - {rt:20} عدد القيود={info['count']:4}  صافي نقدي={info['cash']:>14,.2f}")
            print()


if __name__ == '__main__':
    run()
