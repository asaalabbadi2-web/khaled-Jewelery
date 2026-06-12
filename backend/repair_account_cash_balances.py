"""
repair_account_cash_balances.py
================================
إعادة بناء الأرصدة النقدية المخزّنة (Account.balance_cash) لحسابات الخزائن
من القيود المحاسبية فقط، بحيث تتطابق مع رصيد كشف الحساب لكل خزينة.

المشكلة:
--------
كانت دالة إعادة بناء الأرصدة تجمع حركات السندات (VoucherAccountLine) فوق
حركات القيود المحاسبية (JournalEntryLine) لنفس الحساب. السندات المرحّلة لها
قيد محاسبي تلقائي يسجّل على نفس الحساب بنفس المبلغ، فيُحسب أثر كل سند مرحّل
مرتين، فينحرف رصيد الخزينة الظاهر في شاشة السندات عن رصيد كشف الحساب.

التصحيح:
---------
استدعاء _recalculate_account_balances_for_accounts() بعد إصلاح الدالة
(commit 7bcdf99) لكل حساب مرتبط بخزينة، لإعادة حسابه من JournalEntryLine
فقط (نفس مصدر كشف الحساب).

تشغيل:
------
    cd backend
    python repair_account_cash_balances.py            # dry run
    python repair_account_cash_balances.py --apply    # تطبيق فعلي

    أو في Docker:
    docker cp backend/repair_account_cash_balances.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python /app/backend/repair_account_cash_balances.py
    docker exec yasargold-backend python /app/backend/repair_account_cash_balances.py --apply

الوضع الافتراضي: DRY RUN (لا يُحفظ شيء).
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, Account, SafeBox
from routes import _recalculate_account_balances_for_accounts, _account_weight_balance_main_karat


def run(apply: bool):
    with app.app_context():
        print(f"\n{'=' * 55}")
        print(f"{'تطبيق فعلي' if apply else 'DRY RUN — لن يُحفظ شيء'}")
        print(f"{'=' * 55}\n")

        safe_boxes = [sb for sb in SafeBox.query.all() if sb.account_id]
        account_ids = sorted({sb.account_id for sb in safe_boxes})

        before_cash = {}
        before_weight = {}
        for sb in safe_boxes:
            acc = Account.query.get(sb.account_id)
            before_cash[sb.account_id] = acc.balance_cash or 0.0
            before_weight[sb.account_id] = _account_weight_balance_main_karat(acc)

        _recalculate_account_balances_for_accounts(account_ids)

        print("أرصدة الخزائن (قبل → بعد):")
        any_change = False
        for sb in safe_boxes:
            acc = Account.query.get(sb.account_id)
            old_cash = before_cash[sb.account_id] or 0.0
            new_cash = acc.balance_cash or 0.0
            diff_cash = round(new_cash - old_cash, 2)
            old_weight = before_weight[sb.account_id] or 0.0
            new_weight = _account_weight_balance_main_karat(acc)
            diff_weight = round(new_weight - old_weight, 6)
            marker = ''
            if abs(diff_cash) > 0.005:
                marker += '  <-- نقدي تغيّر'
            if abs(diff_weight) > 0.0005:
                marker += '  <-- وزن تغيّر'
            if marker:
                any_change = True
            print(f"  [{sb.id:3}] {sb.name:40} نقدي: {old_cash:>14,.2f} -> {new_cash:>14,.2f}"
                  f" | وزن: {old_weight:>10,.3f} -> {new_weight:>10,.3f}{marker}")

        if apply:
            db.session.commit()
            print("\n✅ تم الحفظ.")
        else:
            db.session.rollback()
            if any_change:
                print("\n(DRY RUN) لتطبيق التغييرات فعليًا: python repair_account_cash_balances.py --apply")
            else:
                print("\nلا يوجد فرق — الأرصدة متطابقة بالفعل.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='تطبيق التغييرات فعليًا (وإلا dry run)')
    args = parser.parse_args()
    run(apply=args.apply)
