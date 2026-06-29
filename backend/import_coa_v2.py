"""
import_coa_v2.py
================
استيراد حسابات new_accounts_to_import.json مباشرة عبر SQLAlchemy.
يعمل مع SQLite و PostgreSQL.

تشغيل:
    cd backend
    source venv/bin/activate
    DATABASE_URL="postgresql://user:pass@host/db" python import_coa_v2.py

أو بدون DATABASE_URL لاستخدام SQLite المحلي.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, Account
from account_pair_service import link_accounts, unlink_account

# Support: next to script, one level up, or /tmp/
def _find_json():
    candidates = [
        os.path.join(os.path.dirname(__file__), 'new_accounts_to_import.json'),
        os.path.join(os.path.dirname(__file__), '..', 'new_accounts_to_import.json'),
        '/tmp/new_accounts_to_import.json',
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    raise FileNotFoundError(
        "new_accounts_to_import.json not found. Copy it next to the script or to /tmp/."
    )

JSON_PATH = _find_json()

def run():
    with app.app_context():
        db_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        print(f"DB: {db_url[:60]}...")
        print()

        with open(JSON_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)

        accounts_data = data['accounts']

        # ── التحقق من الحسابات الأم (parents) ──────────────────────────────
        parent_numbers = set()
        for row in accounts_data:
            if row.get('parent_account_number'):
                parent_numbers.add(row['parent_account_number'])

        existing_parents = {
            a.account_number: a
            for a in Account.query.filter(
                Account.account_number.in_(list(parent_numbers))
            ).all()
        }

        missing_parents = parent_numbers - set(existing_parents.keys())
        if missing_parents:
            print(f"❌ حسابات أم مفقودة من DB: {sorted(missing_parents)}")
            print("   يجب إنشاؤها أولاً.")
            sys.exit(1)
        else:
            print(f"✅ جميع حسابات الأم موجودة: {sorted(existing_parents.keys())}")

        # ── جلب الحسابات الموجودة ──────────────────────────────────────────
        all_numbers = [r['account_number'] for r in accounts_data]
        existing = {
            a.account_number: a
            for a in Account.query.filter(
                Account.account_number.in_(all_numbers)
            ).all()
        }

        print(f"\nموجود مسبقاً : {sorted(existing.keys()) or 'لا شيء'}")
        print(f"سيُنشأ       : {sorted(n for n in all_numbers if n not in existing) or 'لا شيء'}")
        print()

        created_list, updated_list = [], []
        new_accs = {}

        # ── Pass 1: upsert ─────────────────────────────────────────────────
        for row in accounts_data:
            num = row['account_number']
            acc = existing.get(num)
            if acc is None:
                acc = Account(
                    account_number=num,
                    name=row['name'],
                    type=row['type'],
                    transaction_type=row.get('transaction_type', 'both'),
                    tracks_weight=bool(row.get('tracks_weight', False)),
                )
                db.session.add(acc)
                created_list.append(num)
            else:
                acc.name = row['name']
                acc.type = row['type']
                acc.transaction_type = row.get('transaction_type', acc.transaction_type)
                acc.tracks_weight = bool(row.get('tracks_weight', False))
                updated_list.append(num)
            new_accs[num] = acc

        db.session.flush()

        # ── بناء خريطة شاملة بعد flush ────────────────────────────────────
        all_acc_map = {
            a.account_number: a
            for a in Account.query.filter(
                Account.account_number.in_(
                    all_numbers
                    + [r.get('parent_account_number') for r in accounts_data if r.get('parent_account_number')]
                    + [r.get('memo_account_number') for r in accounts_data if r.get('memo_account_number')]
                )
            ).all()
        }

        # ── Pass 2: روابط parent + memo ────────────────────────────────────
        relinked = 0
        for row in accounts_data:
            acc = new_accs[row['account_number']]
            p_num = row.get('parent_account_number')
            m_num = row.get('memo_account_number')

            new_pid = all_acc_map[p_num].id if p_num and p_num in all_acc_map else None
            new_mid = all_acc_map[m_num].id if m_num and m_num in all_acc_map else None

            memo_changed = acc.memo_account_id != new_mid
            if acc.parent_id != new_pid or memo_changed:
                relinked += 1

            acc.parent_id = new_pid
            db.session.add(acc)

            # الربط/الفسخ عبر الخدمة المركزية فقط -- انظر account_pair_service.py.
            if memo_changed:
                if new_mid is None:
                    unlink_account(acc, created_by='import_coa_v2')
                else:
                    memo_acc = all_acc_map.get(m_num)
                    if memo_acc:
                        link_accounts(acc, memo_acc, created_by='import_coa_v2')

        db.session.commit()

        # ── تقرير ──────────────────────────────────────────────────────────
        print("=" * 50)
        print(f"✅ تم الاستيراد بنجاح")
        print(f"   أُنشئ  : {len(created_list)} حساب  → {created_list or '-'}")
        print(f"   حُدِّث : {len(updated_list)} حساب  → {updated_list or '-'}")
        print(f"   رُبط   : {relinked} علاقة parent/memo")
        print("=" * 50)

        # ── التحقق النهائي ─────────────────────────────────────────────────
        print("\nالتحقق النهائي:")
        final = Account.query.filter(Account.account_number.in_(all_numbers)).all()
        for a in sorted(final, key=lambda x: x.account_number):
            parent = Account.query.get(a.parent_id) if a.parent_id else None
            memo   = Account.query.get(a.memo_account_id) if a.memo_account_id else None
            print(
                f"  {a.account_number:<8} {a.name:<40} "
                f"parent={parent.account_number if parent else '—':<6} "
                f"memo={memo.account_number if memo else '—'}"
            )

if __name__ == '__main__':
    run()
