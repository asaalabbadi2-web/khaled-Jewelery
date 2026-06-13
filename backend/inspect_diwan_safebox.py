"""
inspect_diwan_safebox.py
===========================
يبحث عن خزينة "مكتب الديوان" (أو ما يشبهها بالاسم)، يطبع حسابها المرتبط
ورصيده الحالي لكل عيار، ويتحقق هل حسابها كان من ضمن الحسابات التي عدّلها
سكربت fix_sale_invoice_qty_bug_reversal.py (أي ضمن الـ184 قيد عكسي).

قراءة فقط.

تشغيل:
    docker exec yasargold-backend python backend/inspect_diwan_safebox.py
"""

import os
import sys
import json
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, SafeBox, Account, JournalEntry, JournalEntryLine
from routes import _account_weight_balance_main_karat


def run():
    with app.app_context():
        boxes = SafeBox.query.filter(SafeBox.name.like('%ديوان%')).all()
        if not boxes:
            print("لا توجد خزينة باسم يحتوي 'ديوان'. كل الخزائن:")
            for sb in SafeBox.query.all():
                print(f"  [{sb.id}] {sb.name} (account_id={sb.account_id}, type={sb.safe_type})")
            return

        for sb in boxes:
            print(f"\nخزينة [{sb.id}] {sb.name}  safe_type={sb.safe_type}  account_id={sb.account_id}")
            acc = Account.query.get(sb.account_id) if sb.account_id else None
            if not acc:
                print("  لا يوجد حساب مرتبط.")
                continue
            print(f"  حساب: [{acc.id}] {acc.account_number} {acc.name} tracks_weight={acc.tracks_weight}")
            for k in (18, 21, 22, 24):
                print(f"    balance_{k}k = {getattr(acc, f'balance_{k}k')}")
            print(f"    main-karat total = {_account_weight_balance_main_karat(acc):.3f}")

            # Did our reversal script touch this account?
            cnt = (
                JournalEntryLine.query
                .join(JournalEntry)
                .filter(
                    JournalEntryLine.account_id == acc.id,
                    JournalEntry.reference_type == 'invoice',
                    JournalEntry.description.like('%hist_gold_recon_invoice_reversal%'),
                )
                .count()
            )
            print(f"    عدد أسطر القيود العكسية (hist_gold_recon_invoice_reversal) على هذا الحساب: {cnt}")


if __name__ == '__main__':
    run()
