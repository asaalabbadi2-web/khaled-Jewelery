"""
repair_memo_accounts.py
=======================
إصلاح خطأ في memo_account_id لحسابَي 1074 و 1197.

المشكلة:
---------
- حساب 1072 (مكاتب تسكير فورية وأشخاص) → memo_account_id صحيح = 1074
- حساب 1197 (فور ناين) → memo_account_id = 1074 [خطأ — يشارك مذكرة 1072]
- حساب 1074 (وزني - رقم 72100021) → memo_account_id = 1197 [خطأ — يجب أن يشير لـ 1072]

التصحيح:
---------
- حساب 1074: memo_account_id ← 1072
- حساب 1197: memo_account_id ← None

تشغيل:
------
    python repair_memo_accounts.py          # dry run
    python repair_memo_accounts.py --apply  # تطبيق فعلي
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, Account


def run(apply: bool):
    with app.app_context():
        print(f"\n{'=' * 55}")
        print(f"{'تطبيق فعلي' if apply else 'DRY RUN — لن يُحفظ شيء'}")
        print(f"{'=' * 55}\n")

        acc_1072 = Account.query.get(1072)
        acc_1074 = Account.query.get(1074)
        acc_1197 = Account.query.get(1197)

        for acc, label in [(acc_1072, '1072'), (acc_1074, '1074'), (acc_1197, '1197')]:
            if not acc:
                print(f"  ⚠ حساب {label} غير موجود!")
                return

        print("الحالة الحالية:")
        print(f"  1072 ({acc_1072.name}): memo_account_id = {acc_1072.memo_account_id}")
        print(f"  1074 ({acc_1074.name}): memo_account_id = {acc_1074.memo_account_id}")
        print(f"  1197 ({acc_1197.name}): memo_account_id = {acc_1197.memo_account_id}")
        print()

        print("التغييرات المطلوبة:")
        print(f"  1074: memo_account_id {acc_1074.memo_account_id} → 1072")
        print(f"  1197: memo_account_id {acc_1197.memo_account_id} → None")
        print()

        if apply:
            acc_1074.memo_account_id = 1072
            acc_1197.memo_account_id = None
            db.session.commit()

            print("الحالة بعد الإصلاح:")
            db.session.refresh(acc_1072)
            db.session.refresh(acc_1074)
            db.session.refresh(acc_1197)
            print(f"  1072 ({acc_1072.name}): memo_account_id = {acc_1072.memo_account_id}")
            print(f"  1074 ({acc_1074.name}): memo_account_id = {acc_1074.memo_account_id}")
            print(f"  1197 ({acc_1197.name}): memo_account_id = {acc_1197.memo_account_id}")
            print("\n✅ تم الإصلاح بنجاح.")
        else:
            print("ℹ️  DRY RUN — مرر --apply للتطبيق الفعلي.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    run(apply=args.apply)
