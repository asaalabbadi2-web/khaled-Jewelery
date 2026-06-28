"""
diagnose_1213_vs_1074_balances.py
====================================
تشخيص فقط -- لا يكتب أي شيء.

سبب هذا السكريبت: diagnose_latest_office_reservation.py كشف أن حساب
office.account_category_id (#1072 مكاتب تسكير فورية واشخاص) لديه
memo_account_id = #1213، وهو حساب اسمه الصريح "[غير مستخدم -- مكرَّر،
استُبدل بحساب 1074]" -- أي أن آخر حجز (وربما حجوزات أخرى) سجّلت الذهب
فعلياً على الحساب المتروك #1213 بدل #1074 الصحيح الحالي.

هذا السكريبت يحسب:
  1. الرصيد الحالي لكل من #1213 و#1074 من دفتر الأستاذ مباشرة
     (live_balances_by_account_ids -- المصدر الرسمي الوحيد، كما وحَّدناه
     اليوم في safe_box_balance).
  2. عدد/قائمة كل القيود (JournalEntryLine) التي مسّت #1213 تاريخياً،
     لمعرفة هل هذا الانحراف محصور بآخر حجز فقط أم تراكم عبر حجوزات متعددة.

تشغيل (قراءة فقط):
    docker cp backend/diagnose_1213_vs_1074_balances.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/diagnose_1213_vs_1074_balances.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import Account, JournalEntry, JournalEntryLine
from services.live_balances import live_balances_by_account_ids


def run() -> None:
    with app.app_context():
        acc_1213 = Account.query.get(1213)
        acc_1074 = Account.query.get(1074)

        print("=" * 70)
        for acc in (acc_1213, acc_1074):
            if not acc:
                continue
            live = live_balances_by_account_ids([acc.id]).get(acc.id) or {}
            print(f"\nحساب #{acc.id} {acc.name}")
            print(f"  الرصيد الحالي (دفتر الأستاذ): {live}")

        print("\n" + "=" * 70)
        print("كل سطور القيود التي مسّت #1213 تاريخياً:")
        lines = (
            JournalEntryLine.query
            .filter(JournalEntryLine.account_id == 1213)
            .filter(JournalEntryLine.is_deleted.is_(False))
            .order_by(JournalEntryLine.id.asc())
            .all()
        )
        if not lines:
            print("  لا يوجد أي سطر -- الحساب لم يُستخدم إطلاقاً.")
        for line in lines:
            entry = JournalEntry.query.get(line.journal_entry_id)
            print(
                f"  JE#{entry.id if entry else '?'} ({entry.entry_number if entry else '?'}) "
                f"تاريخ={entry.date if entry else '?'} "
                f"مُرحَّل={entry.is_posted if entry else '?'} "
                f"مرجع={entry.reference_type if entry else '?'}#{entry.reference_id if entry else '?'} | "
                f"مدين_18={line.debit_18k or 0} مدين_21={line.debit_21k or 0} "
                f"مدين_22={line.debit_22k or 0} مدين_24={line.debit_24k or 0} | "
                f"دائن_18={line.credit_18k or 0} دائن_21={line.credit_21k or 0} "
                f"دائن_22={line.credit_22k or 0} دائن_24={line.credit_24k or 0}"
            )


if __name__ == '__main__':
    run()
