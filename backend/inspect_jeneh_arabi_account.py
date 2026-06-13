"""
inspect_jeneh_arabi_account.py
=================================
يبحث عن حساب "شركة الجنيه العربي" (مورد ذهب)، يطبع تفاصيل رصيده الحالي
(balance_18k/21k/22k/24k) كما يظهر على البطاقة/الكشف، وإجمالي القيد
الفعلي (live، من JournalEntryLine) لكل عيار، للمقارنة مع المتوقع:
24k = +482.1 جرام (وما يعادله بالعيار الرئيسي = 550.97 جرام).

قراءة فقط.

تشغيل:
    docker exec yasargold-backend python backend/inspect_jeneh_arabi_account.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, Account, JournalEntry, JournalEntryLine
from routes import convert_to_main_karat, _account_weight_balance_main_karat
from services.live_balances import live_balances_by_account_ids


KARATS = (18, 21, 22, 24)


def run():
    with app.app_context():
        accs = Account.query.filter(Account.name.like('%الجنيه العربي%')).all()
        if not accs:
            print("لم يتم العثور على حساب باسم يحتوي 'الجنيه العربي'.")
            return

        for acc in accs:
            print(f"\n[{acc.id}] {acc.account_number} {acc.name} tracks_weight={acc.tracks_weight}")

            print("  -- balance_Xk (المخزّن / البطاقة):")
            for k in KARATS:
                print(f"     {k}k = {getattr(acc, f'balance_{k}k'):,.3f}")
            print(f"     main-karat total (من balance_Xk) = {_account_weight_balance_main_karat(acc):,.3f}")

            live = live_balances_by_account_ids([acc.id]).get(int(acc.id), {})
            print("  -- live (من JournalEntryLine المباشر):")
            live_main = 0.0
            for k in KARATS:
                v = float(live.get(f'{k}k', 0.0) or 0.0)
                print(f"     {k}k = {v:,.3f}")
                live_main += convert_to_main_karat(v, k)
            print(f"     main-karat total (live) = {live_main:,.3f}")

            # طباعة كل أسطر القيود ذات وزن لهذا الحساب لمعرفة كيف تم توزيعها على العيارات
            lines = (
                JournalEntryLine.query
                .join(JournalEntry)
                .filter(
                    JournalEntryLine.account_id == acc.id,
                    JournalEntry.is_deleted == False,
                    JournalEntryLine.is_deleted == False,
                )
                .order_by(JournalEntry.date.asc())
                .all()
            )
            print(f"  -- عدد أسطر القيود (غير محذوفة): {len(lines)}")
            for l in lines:
                entry = l.journal_entry
                parts = []
                for k in KARATS:
                    d = getattr(l, f'debit_{k}k') or 0.0
                    c = getattr(l, f'credit_{k}k') or 0.0
                    if d or c:
                        parts.append(f"{k}k: debit={d:,.3f} credit={c:,.3f}")
                if parts:
                    posted = getattr(entry, 'is_posted', None)
                    draft = getattr(entry, 'is_draft', None)
                    print(f"     JE[{entry.id}] {entry.date} posted={posted} draft={draft} ref={entry.reference_type}/{entry.reference_id}  " + " | ".join(parts))


if __name__ == '__main__':
    run()
