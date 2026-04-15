"""
fix_weight_misrouted.py
=======================
يصحح قيود الوزن التي ذهبت خطأً إلى حسابات نقدية (transaction_type='cash')
بدلاً من حسابات الوزن (transaction_type='gold') المرتبطة بها.

الاستخدام:
    # عرض فقط (بدون تعديل)
    docker exec yasargold-backend python backend/fix_weight_misrouted.py

    # تطبيق التصحيح
    docker exec yasargold-backend python backend/fix_weight_misrouted.py --apply
"""
from __future__ import annotations

import argparse
import os
import sys

# ─── إعداد Flask ─────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS

app = Flask(__name__)
db_url = os.getenv(
    'DATABASE_URL',
    f"sqlite:///{os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.db')}"
)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
CORS(app)

from models import db, Account, JournalEntryLine  # noqa: E402
db.init_app(app)

WEIGHT_COLS = ['debit_18k', 'credit_18k', 'debit_21k', 'credit_21k',
               'debit_22k', 'credit_22k', 'debit_24k', 'credit_24k']


def _gold_account_for(acc: Account) -> Account | None:
    """يُعيد الحساب الوزني (gold) المقابل لحساب نقدي."""
    # 1) forward memo link pointing to gold account
    if acc.memo_account_id:
        memo = Account.query.get(acc.memo_account_id)
        if memo and (memo.transaction_type or '').lower() == 'gold':
            return memo

    # 2) reverse lookup
    reverse = (
        Account.query
        .filter(Account.memo_account_id == acc.id)
        .filter(Account.transaction_type == 'gold')
        .first()
    )
    return reverse


def run(apply: bool = False):
    with app.app_context():
        print(f"DB: {db_url[:80]}")
        print(f"Mode: {'APPLY' if apply else 'DRY RUN (use --apply to commit)'}")
        print("=" * 70)

        # جلب كل الحسابات النقدية التي لها حركات وزنية
        from sqlalchemy import or_, func, text

        # بناء شرط وجود قيمة وزنية
        weight_condition = or_(
            *[getattr(JournalEntryLine, col) > 0 for col in WEIGHT_COLS]
        )

        misrouted = (
            db.session.query(
                JournalEntryLine.account_id,
                Account.account_number,
                Account.name,
                Account.transaction_type,
                Account.memo_account_id,
                func.count(JournalEntryLine.id).label('line_count'),
                func.sum(JournalEntryLine.debit_21k - JournalEntryLine.credit_21k).label('net_21k'),
                func.sum(JournalEntryLine.debit_18k - JournalEntryLine.credit_18k).label('net_18k'),
                func.sum(JournalEntryLine.debit_22k - JournalEntryLine.credit_22k).label('net_22k'),
                func.sum(JournalEntryLine.debit_24k - JournalEntryLine.credit_24k).label('net_24k'),
            )
            .join(Account, Account.id == JournalEntryLine.account_id)
            .filter(Account.transaction_type == 'cash')
            .filter(weight_condition)
            .group_by(
                JournalEntryLine.account_id,
                Account.account_number,
                Account.name,
                Account.transaction_type,
                Account.memo_account_id,
            )
            .all()
        )

        if not misrouted:
            print("✅ لا توجد قيود وزنية مخطأة في الحسابات النقدية.")
            return

        total_fixed = 0
        errors = []

        for row in misrouted:
            acc_id = row.account_id
            acc = Account.query.get(acc_id)
            gold_acc = _gold_account_for(acc) if acc else None

            print(f"\n{'─'*60}")
            print(f"  حساب خاطئ : [{row.account_number}] {row.name}  (id={acc_id})")
            print(f"  عدد السطور: {row.line_count}")
            print(f"  صافي 21k  : {row.net_21k or 0:.4f} جم")
            print(f"  صافي 18k  : {row.net_18k or 0:.4f} جم")
            print(f"  صافي 22k  : {row.net_22k or 0:.4f} جم")
            print(f"  صافي 24k  : {row.net_24k or 0:.4f} جم")

            if not gold_acc:
                msg = f"  ⚠️  لم يُوجد حساب ذهبي مقابل → تخطي"
                print(msg)
                errors.append(f"لم يُوجد حساب gold لـ {row.account_number}")
                continue

            print(f"  حساب صحيح : [{gold_acc.account_number}] {gold_acc.name}  (id={gold_acc.id})")

            if apply:
                try:
                    updated = (
                        JournalEntryLine.query
                        .filter(JournalEntryLine.account_id == acc_id)
                        .filter(weight_condition)
                        .update({'account_id': gold_acc.id}, synchronize_session=False)
                    )
                    db.session.commit()
                    print(f"  ✅ تم نقل {updated} سطر إلى الحساب الصحيح")
                    total_fixed += updated
                except Exception as e:
                    db.session.rollback()
                    print(f"  ❌ خطأ: {e}")
                    errors.append(str(e))
            else:
                print(f"  → (dry run) سيتم نقل {row.line_count} سطر")

        print(f"\n{'='*70}")
        if apply:
            print(f"✅ تم إصلاح {total_fixed} سطر إجمالاً")
        else:
            print(f"ℹ️  dry run — أعد التشغيل مع --apply لتطبيق التصحيح")
        if errors:
            print(f"⚠️  {len(errors)} تحذير(ات):")
            for e in errors:
                print(f"   - {e}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='تطبيق التصحيح فعلياً')
    args = parser.parse_args()
    run(apply=args.apply)
