"""
find_missing_sbt_jes.py
========================
يطبع تفاصيل القيود المحاسبية المؤثرة على حساب خزينة معيّنة، مع توضيح أيها لم
يُنشئ له SafeBoxTransaction بعد (بحسب ref_type/ref_id). للاستخدام كخطوة
تشخيصية قبل استخدام /admin/sbt-create-from-je/<je_id> لإصلاح خزينة محددة.

قراءة فقط، لا يُغيّر أي شيء.

تشغيل:
    docker cp backend/find_missing_sbt_jes.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/find_missing_sbt_jes.py --safe-box-id 49
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, SafeBox, JournalEntry, JournalEntryLine, SafeBoxTransaction


def run(safe_box_id: int):
    with app.app_context():
        sb = SafeBox.query.get(safe_box_id)
        if not sb or not sb.account_id:
            print("Safe box غير موجود أو بلا حساب مرتبط")
            return

        print(f"[{sb.id}] {sb.name}  (account_id={sb.account_id})\n")

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

        for line in lines:
            entry = line.journal_entry
            rt = (getattr(entry, 'reference_type', None) or '').strip().lower() or '(فارغ/يدوي)'
            w18 = (line.debit_18k or 0) - (line.credit_18k or 0)
            w21 = (line.debit_21k or 0) - (line.credit_21k or 0)
            w22 = (line.debit_22k or 0) - (line.credit_22k or 0)
            w24 = (line.debit_24k or 0) - (line.credit_24k or 0)
            cash = (line.cash_debit or 0) - (line.cash_credit or 0)

            has_w = any(abs(v) > 0.0005 for v in (w18, w21, w22, w24))
            has_cash = abs(cash) > 0.005
            if not has_w and not has_cash:
                continue

            # Check if any SBT references this JE (any ref_type)
            sbt_count = SafeBoxTransaction.query.filter_by(
                safe_box_id=sb.id, ref_id=entry.id
            ).filter(SafeBoxTransaction.ref_type.in_(
                [rt, 'voucher', 'invoice', 'office_reservation', 'je_correction']
            )).count()

            print(f"  JE id={entry.id:6} entry_number={getattr(entry, 'entry_number', None)!s:12} "
                  f"date={getattr(entry, 'date', None)} reference_type={rt:18} "
                  f"is_posted={getattr(entry, 'is_posted', None)} is_draft={getattr(entry, 'is_draft', None)} "
                  f"cash={cash:>12,.2f} w18={w18:>9,.3f} w21={w21:>9,.3f} w22={w22:>9,.3f} w24={w24:>9,.3f} "
                  f"sbt_rows_for_je={sbt_count}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--safe-box-id', type=int, required=True)
    args = parser.parse_args()
    run(args.safe_box_id)
