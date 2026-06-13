"""
check_account_safebox_mapping.py
==================================
يفحص: هل حساب 760 (مخزون الذهب المعروض للبيع وزني) مرتبط بأكثر من خزينة
(SafeBox) واحدة؟ وإن وُجدت خزائن أخرى، هل هي نشطة وما هو نوعها؟

أيضًا يطبع كل الخزائن الذهبية النشطة مع account_id الخاص بكل منها، للتأكد
من عدم وجود تداخل (أكثر من خزينة على نفس الحساب) لأي حساب آخر أيضًا.

قراءة فقط.

تشغيل:
    docker cp backend/check_account_safebox_mapping.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/check_account_safebox_mapping.py
"""

import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, SafeBox, Account


def run():
    with app.app_context():
        print("=" * 60)
        print("كل الخزائن المرتبطة بحساب 760")
        print("=" * 60)
        boxes = SafeBox.query.filter_by(account_id=760).all()
        for sb in boxes:
            print(f"  [{sb.id}] {sb.name}  safe_type={sb.safe_type} is_active={sb.is_active}")

        print("\n" + "=" * 60)
        print("فحص تكرار account_id بين كل الخزائن (نشطة وغير نشطة)")
        print("=" * 60)
        by_acc = defaultdict(list)
        for sb in SafeBox.query.all():
            if sb.account_id:
                by_acc[sb.account_id].append(sb)
        for acc_id, sbs in by_acc.items():
            if len(sbs) > 1:
                acc = Account.query.get(acc_id)
                print(f"  account[{acc_id}] {acc.name if acc else '?'}:")
                for sb in sbs:
                    print(f"      [{sb.id}] {sb.name}  safe_type={sb.safe_type} is_active={sb.is_active}")


if __name__ == '__main__':
    run()
