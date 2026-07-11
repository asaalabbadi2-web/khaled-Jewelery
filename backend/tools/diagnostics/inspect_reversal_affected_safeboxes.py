"""
inspect_reversal_affected_safeboxes.py
=========================================
يقرأ تقرير fix_sale_invoice_qty_bug_reversal.py (الذي تم تطبيقه)، يجمع كل
الحسابات التي عُدّلت (من reversal_lines لكل فاتورة) مع صافي التعديل لكل
عيار، ثم يبحث: أي من هذه الحسابات مرتبط بخزينة (SafeBox.account_id)،
ويطبع لكل خزينة من هذه: اسمها، صافي التعديل لكل عيار، ورصيدها الحالي
(balance_Xk) لمعرفة هل أصبح سالبًا أو صفرًا بسبب التصحيح.

قراءة فقط.

تشغيل:
    docker exec yasargold-backend python backend/inspect_reversal_affected_safeboxes.py --report <path>
"""

import os
import sys
import json
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, SafeBox, Account


KARATS = (18, 21, 22, 24)


def run(report_path: str):
    with app.app_context():
        with open(report_path, 'r', encoding='utf-8') as f:
            report = json.load(f)

        # net adjustment per account per karat = sum over invoices of
        # (sum of rev_debit_k - sum of rev_credit_k)
        net_by_account = defaultdict(lambda: {k: 0.0 for k in KARATS})

        for inv in report.get('invoices', []):
            for line in inv.get('reversal_lines', []):
                acc_id = line['account_id']
                for k_str, amt in line.get('debit', {}).items():
                    net_by_account[acc_id][int(k_str)] += amt
                for k_str, amt in line.get('credit', {}).items():
                    net_by_account[acc_id][int(k_str)] -= amt

        print(f"عدد الحسابات المعدّلة: {len(net_by_account)}\n")

        # All safe boxes, indexed by account_id
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
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    run(report_path=args.report)
