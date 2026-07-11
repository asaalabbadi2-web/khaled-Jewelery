"""
find_valuation_diff_account.py
=================================
يبحث عن حساب "فروقات تقييم وزنية" (أو ما يشبهه) بأي رقم حساب، لأن رقم 7600
المتوقع من config.py غير موجود في قاعدة بيانات الإنتاج.

قراءة فقط.

تشغيل:
    docker exec yasargold-backend python backend/find_valuation_diff_account.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, Account


def run():
    with app.app_context():
        rows = Account.query.filter(Account.name.like('%فروقات%')).all()
        for a in rows:
            print(f"id={a.id:5} number={a.account_number:10} name={a.name!r} "
                  f"type={a.type} tracks_weight={a.tracks_weight}")
        if not rows:
            print("لا توجد حسابات تحتوي 'فروقات' في الاسم.")


if __name__ == '__main__':
    run()
