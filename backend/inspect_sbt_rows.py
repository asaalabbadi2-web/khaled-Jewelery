"""
inspect_sbt_rows.py
====================
يطبع كل صفوف SafeBoxTransaction التي safe_box_id و ref_id محددين، لمعرفة
ما تمثله بالفعل (ref_type, invoice_id, الوزن, التاريخ) - للتأكد من أن
ref_id=<je_id> يعني فعلاً "حركة هذا القيد" وليس تطابقاً عرضياً مع رقم
فاتورة/سند آخر.

قراءة فقط.

تشغيل:
    docker cp backend/inspect_sbt_rows.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/inspect_sbt_rows.py --safe-box-id 41 --ref-ids 29,76,1222
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, SafeBoxTransaction, JournalEntry


def run(safe_box_id: int, ref_ids):
    with app.app_context():
        for ref_id in ref_ids:
            rows = SafeBoxTransaction.query.filter_by(safe_box_id=safe_box_id, ref_id=ref_id).all()
            print(f"\n--- safe_box_id={safe_box_id} ref_id={ref_id} ({len(rows)} صف) ---")
            for r in rows:
                print(f"  id={r.id} ref_type={r.ref_type!r} invoice_id={getattr(r, 'invoice_id', None)} "
                      f"direction={r.direction} amount_cash={r.amount_cash} "
                      f"w18={r.weight_18k} w21={r.weight_21k} w22={r.weight_22k} w24={r.weight_24k} "
                      f"created_at={getattr(r, 'created_at', None)} notes={r.notes!r}")
            je = JournalEntry.query.get(ref_id)
            if je:
                print(f"  (للمقارنة) JE {ref_id}: entry_number={getattr(je,'entry_number',None)} "
                      f"reference_type={getattr(je,'reference_type',None)!r} date={getattr(je,'date',None)}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--safe-box-id', type=int, required=True)
    parser.add_argument('--ref-ids', type=str, required=True)
    args = parser.parse_args()
    ref_ids = [int(x.strip()) for x in args.ref_ids.split(',') if x.strip()]
    run(args.safe_box_id, ref_ids)
