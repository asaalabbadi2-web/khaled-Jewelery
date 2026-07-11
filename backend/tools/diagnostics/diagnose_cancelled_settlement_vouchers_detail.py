"""
diagnose_cancelled_settlement_vouchers_detail.py
====================================================
تشخيص فقط -- لا يكتب أي شيء.

متابعة لـdiagnose_cancelled_settlement_impact.py: ذاك السكريبت وجد 4 سندات
تسوية ملغاة (AV-2026-00130, 00131, 00132, 00223) أثّرت على 9 دفعات
بإجمالي 27,820. هذا السكريبت يطبع التفاصيل الكاملة لكل سند ملغى (السبب،
الملاحظات، تاريخ الإلغاء، القيد المحاسبي المرتبط وحالته) + كل AuditLog
مرتبط، للتمييز بين ما عولج سابقاً بطريقة أخرى وما لا يزال معلَّقاً فعلياً
-- وتحديداً لتحديد سند تصحيح خطأ إدخال نقدي بحساب مدى بمبلغ 8850.

تشغيل (قراءة فقط):
    docker exec yasargold-backend python backend/diagnose_cancelled_settlement_vouchers_detail.py
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, Voucher, VoucherAccountLine, AuditLog, JournalEntry, SettlementLine

VOUCHER_NUMBERS = ['AV-2026-00130', 'AV-2026-00131', 'AV-2026-00132', 'AV-2026-00223']


def run():
    with app.app_context():
        for vn in VOUCHER_NUMBERS:
            v = Voucher.query.filter_by(voucher_number=vn).first()
            print('=' * 70)
            if not v:
                print(f"{vn}: غير موجود!")
                continue
            print(f"{vn} (id={v.id})")
            print(f"  status              : {v.status}")
            print(f"  voucher_type/ref_type: {v.voucher_type} / {getattr(v, 'reference_type', None)}")
            print(f"  date                 : {v.date}")
            print(f"  amount_cash/gold     : {v.amount_cash} / {v.amount_gold}")
            print(f"  created_by           : {getattr(v, 'created_by', None)}")
            print(f"  cancellation_reason  : {v.cancellation_reason}")
            print(f"  cancelled_at         : {v.cancelled_at}")
            notes = getattr(v, 'notes', None)
            if notes:
                try:
                    parsed = json.loads(notes)
                    print(f"  notes (parsed)       : {json.dumps(parsed, ensure_ascii=False, indent=4)}")
                except Exception:
                    print(f"  notes (raw)          : {notes}")

            je_id = getattr(v, 'journal_entry_id', None)
            if je_id:
                je = JournalEntry.query.get(je_id)
                print(f"  journal_entry_id     : {je_id} (exists={je is not None})")

            lines = VoucherAccountLine.query.filter_by(voucher_id=v.id).all()
            print(f"  account lines ({len(lines)}):")
            for ln in lines:
                print(f"    - account_id={ln.account_id} | {ln.line_type} | {ln.amount_type} | {ln.amount} | {ln.description}")

            sls = SettlementLine.query.filter_by(voucher_id=v.id).all()
            print(f"  settlement lines ({len(sls)}):")
            for sl in sls:
                print(f"    - invoice_payment_id={sl.invoice_payment_id} | amount_settled={sl.amount_settled}")

            logs = AuditLog.query.filter(
                AuditLog.entity_type == 'Voucher',
                AuditLog.entity_number == vn,
            ).order_by(AuditLog.id.asc()).all()
            print(f"  audit log entries ({len(logs)}):")
            for log in logs:
                print(f"    - [{log.created_at if hasattr(log, 'created_at') else '?'}] action={log.action} user={log.user_name} success={log.success}")
                if log.details:
                    try:
                        print(f"        details: {json.dumps(json.loads(log.details), ensure_ascii=False)}")
                    except Exception:
                        print(f"        details: {log.details}")
            print()


if __name__ == '__main__':
    run()
