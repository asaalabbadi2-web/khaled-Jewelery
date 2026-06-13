"""
inspect_account_836.py
========================
فحص حساب "خسارة الوزن (الفقد) وزني" [836]: هل هو مرتبط بخزينة؟ ما هي
كل الحركات المسجلة عليه؟ هل JE 28 هو الحركة الوحيدة؟

قراءة فقط.

تشغيل:
    docker cp backend/inspect_account_836.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/inspect_account_836.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, Account, SafeBox, JournalEntry, JournalEntryLine
from routes import convert_to_main_karat


def net_main_karat(line):
    total = 0.0
    for k in (18, 21, 22, 24):
        w = (getattr(line, f'debit_{k}k') or 0) - (getattr(line, f'credit_{k}k') or 0)
        total += convert_to_main_karat(w, k)
    return total


def run():
    with app.app_context():
        acc = Account.query.get(836)
        print(f"حساب [836] {acc.name if acc else '?'} (type={getattr(acc,'account_type',None)})")

        sb = SafeBox.query.filter_by(account_id=836).first()
        print(f"مرتبط بخزينة؟ {sb.name if sb else 'لا'}\n")

        lines = (
            JournalEntryLine.query
            .join(JournalEntry)
            .filter(
                JournalEntryLine.account_id == 836,
                JournalEntry.is_deleted == False,
                JournalEntryLine.is_deleted == False,
                JournalEntry.is_posted == True,
            )
            .all()
        )
        total = 0.0
        for line in lines:
            entry = line.journal_entry
            nmk = net_main_karat(line)
            total += nmk
            print(f"  JE {entry.id} ({getattr(entry,'entry_number',None)}) date={getattr(entry,'date',None)} "
                  f"entry_type={getattr(entry,'entry_type',None)!r} reference_type={getattr(entry,'reference_type',None)!r} "
                  f"description={getattr(entry,'description',None)!r} "
                  f"net={nmk:>10,.3f}  "
                  f"w18={(line.debit_18k or 0)-(line.credit_18k or 0):.3f} "
                  f"w21={(line.debit_21k or 0)-(line.credit_21k or 0):.3f}")
        print(f"\nإجمالي الحساب [836] = {total:,.3f}")


if __name__ == '__main__':
    run()
