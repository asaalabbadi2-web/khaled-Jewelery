"""
repair_balances.py
==================
تصحيح الأرصدة التاريخية الخاطئة في حسابات المخزون.

المشكلة:
--------
النظام القديم كان يُدين حساب المخزون النقدي (1310) عند:
  1. تنفيذ حجوزات المكاتب (office_reservation)
  2. مشتريات ذهب من عملاء (شراء من عميل)
الصحيح أن يُدين حساب المشتريات (512) لأن هذه معاملة شراء حقيقية.

التصحيح:
---------
  مدين:  512  (مشتريات ذهب كسر)    ← تسجيل تكلفة الشراء
  دائن:  1310 (مخزون ذهب كسر)     ← إلغاء القيد الخاطئ

تشغيل:
------
    cd backend
    source venv/bin/activate
    python repair_balances.py

    أو في Docker:
    docker cp backend/repair_balances.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python /app/backend/repair_balances.py

الوضع الافتراضي: DRY RUN (لا يُحفظ شيء).
لتطبيق التصحيح الفعلي مرر: --apply
"""

import os
import sys
import argparse
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, Account, JournalEntry, JournalEntryLine


# ─── أرقام الحسابات ────────────────────────────────────────────────────────
INVENTORY_SCRAP_NUMBER  = '1310'   # مخزون ذهب كسر (فيه القيد الخاطئ)
PURCHASES_SCRAP_NUMBER  = '512'    # مشتريات ذهب كسر (الحساب الصحيح)
INVENTORY_MAIN_NUMBER   = '1300'   # مخزون ذهب رئيسي (فيه دائن COGS خاطئ)
COGS_NUMBER             = '521'    # تكلفة مبيعات الذهب (فيه مدين COGS خاطئ)
CORRECTION_DATE         = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
CORRECTION_ENTRY_PREFIX = 'CORR-BAL'


def _get_acc(number: str) -> Account:
    acc = Account.query.filter_by(account_number=number).first()
    if not acc:
        raise ValueError(f'حساب {number} غير موجود في قاعدة البيانات')
    return acc


def _calc_wrong_debit_1310(inventory_acc_id: int) -> Decimal:
    """إجمالي cash_debit الخاطئ في 1310 من office_reservation وشراء من عميل"""
    from sqlalchemy import text

    sql = text("""
        SELECT COALESCE(SUM(jl.cash_debit), 0)
        FROM journal_entry_line jl
        JOIN journal_entry je ON je.id = jl.journal_entry_id
        WHERE jl.account_id = :acc_id
          AND jl.cash_debit > 0
          AND je.is_deleted = false
          AND (
            je.reference_type = 'office_reservation'
            OR EXISTS (
              SELECT 1 FROM invoice i
              WHERE i.id = je.reference_id
                AND je.reference_type = 'invoice'
                AND i.invoice_type = 'شراء من عميل'
            )
          )
    """)
    result = db.session.execute(sql, {'acc_id': inventory_acc_id}).scalar()
    return Decimal(str(result or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _calc_wrong_credit_1300(inventory_acc_id: int) -> Decimal:
    """إجمالي cash_credit الخاطئ في 1300 من قيود COGS للمبيعات"""
    from sqlalchemy import text

    sql = text("""
        SELECT COALESCE(SUM(jl.cash_credit), 0)
        FROM journal_entry_line jl
        JOIN journal_entry je ON je.id = jl.journal_entry_id
        WHERE jl.account_id = :acc_id
          AND jl.cash_credit > 0
          AND je.is_deleted = false
          AND EXISTS (
            SELECT 1 FROM invoice i
            WHERE i.id = je.reference_id
              AND je.reference_type = 'invoice'
              AND i.invoice_type = 'بيع'
          )
    """)
    result = db.session.execute(sql, {'acc_id': inventory_acc_id}).scalar()
    return Decimal(str(result or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)



def run(apply: bool = False):
    with app.app_context():
        db_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        print(f'DB: {db_url[:60]}...')
        print()

        inv_scrap  = _get_acc(INVENTORY_SCRAP_NUMBER)   # 1310
        pur_scrap  = _get_acc(PURCHASES_SCRAP_NUMBER)   # 512
        inv_main   = _get_acc(INVENTORY_MAIN_NUMBER)    # 1300
        cogs_acc   = _get_acc(COGS_NUMBER)              # 521

        wrong_1310 = _calc_wrong_debit_1310(inv_scrap.id)
        wrong_1300 = _calc_wrong_credit_1300(inv_main.id)

        print('=' * 60)
        print('تقرير التصحيح:')
        print()
        print(f'  [A] 1310 — مدين خاطئ (مكاتب + عملاء): {wrong_1310:>15,.2f} ريال')
        print(f'      التصحيح: Dr.512 / Cr.1310')
        print()
        print(f'  [B] 1300 — دائن خاطئ (COGS مبيعات):   {wrong_1300:>15,.2f} ريال')
        print(f'      التصحيح: Dr.1300 / Cr.521')
        print('=' * 60)

        if wrong_1310 <= 0 and wrong_1300 <= 0:
            print('✅ لا توجد مبالغ خاطئة — لا يلزم تصحيح.')
            return

        if not apply:
            print()
            print('⚠️  وضع DRY RUN — لم يُطبَّق أي تغيير.')
            print('    لتطبيق التصحيح شغّل: python repair_balances.py --apply')
            return

        now = datetime.now(timezone.utc)

        # ──── [A] تصحيح 1310 ────────────────────────────────────────────────
        if wrong_1310 > 0:
            je_a = JournalEntry(
                entry_number=f'{CORRECTION_ENTRY_PREFIX}-1310',
                date=CORRECTION_DATE,
                description='تصحيح: نقل مشتريات المكاتب والعملاء من مخزون 1310 إلى مشتريات 512',
                reference_type='balance_correction',
                reference_id=None,
                is_posted=True,
                posted_at=now,
                posted_by='repair_balances.py',
                entry_type='تصحيح',
            )
            db.session.add(je_a)
            db.session.flush()

            db.session.add(JournalEntryLine(
                journal_entry_id=je_a.id,
                account_id=pur_scrap.id,
                cash_debit=float(wrong_1310),
                cash_credit=0.0,
                description='تصحيح: مشتريات ذهب مكاتب وعملاء — منقولة من 1310',
            ))
            db.session.add(JournalEntryLine(
                journal_entry_id=je_a.id,
                account_id=inv_scrap.id,
                cash_debit=0.0,
                cash_credit=float(wrong_1310),
                description='تصحيح: إلغاء قيد مخزون خاطئ في 1310',
            ))
            print(f'✅ [A] قيد 1310 → 512: {wrong_1310:,.2f} ريال  [{je_a.entry_number}]')

        # ──── [B] تصحيح 1300 ────────────────────────────────────────────────
        if wrong_1300 > 0:
            je_b = JournalEntry(
                entry_number=f'{CORRECTION_ENTRY_PREFIX}-1300',
                date=CORRECTION_DATE,
                description='تصحيح: عكس قيود COGS الخاطئة من مخزون 1300 وتكلفة مبيعات 521',
                reference_type='balance_correction',
                reference_id=None,
                is_posted=True,
                posted_at=now,
                posted_by='repair_balances.py',
                entry_type='تصحيح',
            )
            db.session.add(je_b)
            db.session.flush()

            db.session.add(JournalEntryLine(
                journal_entry_id=je_b.id,
                account_id=inv_main.id,
                cash_debit=float(wrong_1300),
                cash_credit=0.0,
                description='تصحيح: عكس دائن COGS خاطئ في 1300',
            ))
            db.session.add(JournalEntryLine(
                journal_entry_id=je_b.id,
                account_id=cogs_acc.id,
                cash_debit=0.0,
                cash_credit=float(wrong_1300),
                description='تصحيح: عكس مدين COGS خاطئ في 521',
            ))
            print(f'✅ [B] قيد 1300 → 521: {wrong_1300:,.2f} ريال  [{je_b.entry_number}]')

        db.session.commit()
        print()
        print('✅ تم حفظ جميع قيود التصحيح بنجاح!')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='تصحيح الأرصدة التاريخية')
    parser.add_argument('--apply', action='store_true',
                        help='طبّق التصحيح فعلياً (بدونه: dry run)')
    args = parser.parse_args()
    run(apply=args.apply)
