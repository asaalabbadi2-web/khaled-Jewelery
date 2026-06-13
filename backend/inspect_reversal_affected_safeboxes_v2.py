"""
inspect_reversal_affected_safeboxes_v2.py
============================================
نسخة لا تعتمد على ملف تقرير JSON (قد لا يكون موجوداً إن أُعيد تشغيل
الحاوية). تقرأ مباشرة من قاعدة البيانات كل أسطر القيود التي أنشأها
fix_sale_invoice_qty_bug_reversal.py --apply (يُحدَّدها عبر
description LIKE '%hist_gold_recon_invoice_reversal%')، تجمع صافي
التعديل لكل حساب/عيار، ثم تبحث: أي من هذه الحسابات مرتبط بخزينة
(SafeBox.account_id)، وتطبع رصيدها الحالي.

قراءة فقط.

تشغيل:
    docker exec yasargold-backend python backend/inspect_reversal_affected_safeboxes_v2.py
"""

import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, SafeBox, Account, JournalEntry, JournalEntryLine


KARATS = (18, 21, 22, 24)
REF_TAG = 'hist_gold_recon_invoice_reversal'


def run():
    with app.app_context():
        lines = (
            JournalEntryLine.query
            .join(JournalEntry)
            .filter(
                JournalEntry.description.like(f'%{REF_TAG}%'),
                JournalEntryLine.is_deleted == False,
            )
            .all()
        )

        print(f"عدد أسطر القيود العكسية: {len(lines)}")
        je_ids = set(l.journal_entry_id for l in lines)
        print(f"عدد القيود العكسية: {len(je_ids)}\n")

        net_by_account = defaultdict(lambda: {k: 0.0 for k in KARATS})
        for l in lines:
            for k in KARATS:
                d = getattr(l, f'debit_{k}k') or 0.0
                c = getattr(l, f'credit_{k}k') or 0.0
                if d or c:
                    net_by_account[l.account_id][k] += (d - c)

        boxes_by_account = defaultdict(list)
        for sb in SafeBox.query.all():
            if sb.account_id:
                boxes_by_account[sb.account_id].append(sb)

        for acc_id, deltas in sorted(net_by_account.items()):
            acc = Account.query.get(acc_id)
            sbs = boxes_by_account.get(acc_id, [])
            tag = " <== مرتبط بخزينة!" if sbs else ""
            print(f"حساب [{acc_id}] {acc.account_number if acc else '?'} {acc.name if acc else '?'}{tag}")
            for k in KARATS:
                if abs(deltas[k]) > 1e-6:
                    bal = getattr(acc, f'balance_{k}k') if acc else None
                    print(f"    عيار {k}: صافي التعديل={deltas[k]:>10,.3f}   الرصيد الحالي={bal:>10,.3f}")
            for sb in sbs:
                print(f"    >> خزينة [{sb.id}] {sb.name} (safe_type={sb.safe_type})")
            print()


if __name__ == '__main__':
    run()
