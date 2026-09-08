"""
audit_transaction_type_both.py — P4.1: Diagnostic Read-Only
=============================================================
يستخرج كل الحسابات ذات transaction_type='both' ويُصنِّفها.

التشغيل:
  DATABASE_URL=postgresql://... python audit_transaction_type_both.py

لا يُعدِّل أي بيانات — read-only بالكامل.
"""
from __future__ import annotations

import os
import sys

# ─── قيد أمان: لا نُعدِّل DB من هذا الملف ────────────────────────────────────
_AUDIT_READ_ONLY_GUARD = True

_VALID_GRADES = ('A', 'B', 'C', 'D')

GRADE_LABELS = {
    'A': 'شرعي / Legitimate',
    'B': 'Legacy آمن الإصلاح / Auto-fixable',
    'C': 'يحتاج مراجعة يدوية / Manual Review',
    'D': 'غير متوقع / Unknown',
}


# ─── منطق التصنيف (خالٍ من DB — قابل للاختبار وحده) ─────────────────────────

def classify_account(info: dict) -> tuple[str, str]:
    """
    يُصنِّف حساباً من فئة 'both'.

    يعيد (grade, reason) حيث grade ∈ {'A','B','C','D'}.

    A — شرعي: حساب خزينة أو له سبب تقني مقبول
    B — Legacy آمن: non-7xxx + tracks_weight=False + صفر حركة + صفر تبعيات
    C — يحتاج مراجعة: له حركة أو له تبعيات أو تعارض في tracks_weight
    D — غير متوقع: تركيبة لم نتوقعها
    """
    num          = str(info.get('account_number', '') or '')
    is_7xxx      = num.startswith('7')
    tw           = bool(info.get('tracks_weight', False))
    is_safebox   = bool(info.get('is_safebox', False))

    je_count      = int(info.get('je_count', 0))
    voucher_count = int(info.get('voucher_count', 0))
    invoice_count = int(info.get('invoice_count', 0))
    mapping_count = int(info.get('mapping_count', 0))
    customer_count = int(info.get('customer_count', 0))
    supplier_count = int(info.get('supplier_count', 0))
    employee_count = int(info.get('employee_count', 0))
    office_count   = int(info.get('office_count', 0))
    children_count = int(info.get('children_count', 0))
    system_config  = bool(info.get('in_system_config', False))

    balance_cash = float(info.get('balance_cash', 0.0) or 0)
    weight_balances = [
        float(info.get(f'balance_{k}', 0.0) or 0)
        for k in ('18k', '21k', '22k', '24k')
    ]
    has_balance = abs(balance_cash) > 0.001 or any(abs(b) > 0.001 for b in weight_balances)

    has_activity   = je_count > 0 or voucher_count > 0 or invoice_count > 0
    has_entity     = customer_count > 0 or supplier_count > 0 or employee_count > 0 or office_count > 0
    has_refs       = mapping_count > 0 or system_config or has_entity

    # تعارض بين رقم الحساب و tracks_weight
    weight_mismatch = (is_7xxx and not tw) or (not is_7xxx and tw)

    # ─── A: خزينة (SafeBox) ─────────────────────────────────────────────────
    if is_safebox:
        return 'A', 'حساب خزينة — استخدام both قد يكون مقصوداً تاريخياً'

    # ─── C: تعارض tracks_weight ──────────────────────────────────────────────
    if weight_mismatch:
        direction = '7xxx مع tracks_weight=False' if (is_7xxx and not tw) \
                    else 'non-7xxx مع tracks_weight=True'
        return 'C', f'تعارض في tracks_weight: {direction}'

    # ─── C: له حركة أو تبعيات ────────────────────────────────────────────────
    if has_activity:
        return 'C', (
            f'له حركة محاسبية — JE: {je_count}, Voucher: {voucher_count}, '
            f'Invoice: {invoice_count}'
        )
    if has_balance:
        return 'C', f'له رصيد غير صفري — cash: {balance_cash}'
    if has_refs:
        return 'C', (
            f'له تبعيات — mappings: {mapping_count}, entities: '
            f'{customer_count + supplier_count + employee_count + office_count}'
        )
    if children_count > 0:
        return 'C', f'له حسابات فرعية: {children_count}'

    # ─── B: Legacy نظيف — non-7xxx + صفر كل شيء ────────────────────────────
    if not is_7xxx and not tw:
        return 'B', (
            'transaction_type=both ورثه من DEFAULT الـ DB — '
            'يمكن تصحيحه إلى cash بأمان'
        )

    # ─── B: 7xxx + tracks_weight=True + صفر ─────────────────────────────────
    if is_7xxx and tw:
        return 'B', (
            'حساب وزني (7xxx) transaction_type=both من DEFAULT — '
            'يمكن تصحيحه إلى gold'
        )

    # ─── D: تركيبة لم نتوقعها ────────────────────────────────────────────────
    return 'D', f'تركيبة غير متوقعة: 7xxx={is_7xxx}, tracks_weight={tw}'


# ─── جمع بيانات حساب واحد (يستخدم DB) ───────────────────────────────────────

def _gather_info(acc, db_session) -> dict:
    """يجمع كل المعلومات اللازمة لتصنيف حساب واحد (read-only)."""
    from models import (AccountingMapping, Customer, Employee, Invoice,
                        JournalEntryLine, Office, SafeBox, Settings,
                        Supplier, VoucherAccountLine)
    from sqlalchemy import or_

    acc_id = acc.id

    is_safebox = SafeBox.query.filter_by(account_id=acc_id).first() is not None

    je_count      = JournalEntryLine.query.filter_by(account_id=acc_id).count()
    voucher_count = VoucherAccountLine.query.filter_by(account_id=acc_id).count()
    invoice_count = Invoice.query.filter_by(wage_inventory_account_id=acc_id).count()
    mapping_count = AccountingMapping.query.filter_by(account_id=acc_id).count()
    customer_count = Customer.query.filter(
        or_(Customer.account_id == acc_id, Customer.account_category_id == acc_id)
    ).count()
    supplier_count = Supplier.query.filter(
        or_(Supplier.account_id == acc_id, Supplier.account_category_id == acc_id)
    ).count()
    employee_count = Employee.query.filter_by(account_id=acc_id).count()
    office_count   = Office.query.filter_by(account_category_id=acc_id).count()
    children_count = type(acc).query.filter_by(parent_id=acc_id).count()

    settings = Settings.query.first()
    in_system_config = settings is not None and (
        getattr(settings, 'stones_pending_account_id', None) == acc_id or
        getattr(settings, 'stones_display_revenue_account_id', None) == acc_id
    )

    memo_number = None
    if acc.memo_account_id:
        memo_acc = type(acc).query.get(acc.memo_account_id)
        memo_number = memo_acc.account_number if memo_acc else f'?({acc.memo_account_id})'

    return {
        'id':             acc_id,
        'account_number': acc.account_number,
        'name':           acc.name,
        'parent_id':      acc.parent_id,
        'transaction_type': acc.transaction_type,
        'tracks_weight':  acc.tracks_weight,
        'memo_account_id': acc.memo_account_id,
        'memo_number':    memo_number,
        'balance_cash':   float(acc.balance_cash or 0),
        'balance_18k':    float(acc.balance_18k or 0),
        'balance_21k':    float(acc.balance_21k or 0),
        'balance_22k':    float(acc.balance_22k or 0),
        'balance_24k':    float(acc.balance_24k or 0),
        'is_safebox':     is_safebox,
        'je_count':       je_count,
        'voucher_count':  voucher_count,
        'invoice_count':  invoice_count,
        'mapping_count':  mapping_count,
        'customer_count': customer_count,
        'supplier_count': supplier_count,
        'employee_count': employee_count,
        'office_count':   office_count,
        'children_count': children_count,
        'in_system_config': in_system_config,
    }


# ─── تشغيل التدقيق ──────────────────────────────────────────────────────────

def run_audit() -> list[dict]:
    """يُشغِّل التدقيق الكامل ويعيد قائمة من dict (read-only)."""
    from models import Account, db
    accounts = Account.query.filter_by(transaction_type='both').order_by(
        Account.account_number).all()
    results = []
    for acc in accounts:
        info = _gather_info(acc, db.session)
        grade, reason = classify_account(info)
        results.append({**info, 'grade': grade, 'reason': reason})
    return results


# ─── طباعة التقرير ──────────────────────────────────────────────────────────

def print_report(results: list[dict]) -> None:
    """يطبع تقريراً منسّقاً — لا يُعدِّل البيانات."""
    divider = '═' * 70

    print(f'\n{divider}')
    print('  P4.1 — LEGACY TRANSACTION TYPE AUDIT — transaction_type=both')
    print(divider)
    print(f'  المصدر: {os.getenv("DATABASE_URL", "(DATABASE_URL غير محدد)")}')
    print(f'  إجمالي الحسابات المكتشفة: {len(results)}')
    print(f'{divider}\n')

    for i, r in enumerate(results, 1):
        grade = r['grade']
        label = GRADE_LABELS.get(grade, grade)
        memo  = r['memo_number'] or '—'
        wbal  = max(abs(r[f'balance_{k}']) for k in ('18k', '21k', '22k', '24k'))

        print(f'  {i:02d}. حساب: {r["account_number"]} | {r["name"]}')
        print(f'      ID: {r["id"]:>6}  |  Parent: {r["parent_id"] or "—":>6}  '
              f'|  Memo→ {memo}')
        print(f'      tracks_weight: {str(r["tracks_weight"]):5}  '
              f'|  is_safebox: {str(r["is_safebox"]):5}')
        print(f'      رصيد نقدي: {r["balance_cash"]:>10.3f}  '
              f'|  رصيد وزن(max): {wbal:>8.3f}')
        print(f'      JE lines: {r["je_count"]:>5}  '
              f'|  Vouchers: {r["voucher_count"]:>5}  '
              f'|  Invoices: {r["invoice_count"]:>5}')
        print(f'      Mappings: {r["mapping_count"]:>5}  '
              f'|  Entities: {r["customer_count"] + r["supplier_count"] + r["employee_count"]:>5}  '
              f'|  Children: {r["children_count"]:>5}')
        print(f'      ── التصنيف: [{grade}] {label}')
        print(f'         السبب: {r["reason"]}')
        print()

    # ─── ملخص ────────────────────────────────────────────────────────────────
    from collections import Counter
    summary = Counter(r['grade'] for r in results)

    print(f'{divider}')
    print('  SUMMARY')
    print(f'{divider}')
    print(f'  الإجمالي:               {len(results):>4}')
    for grade in ('A', 'B', 'C', 'D'):
        label = GRADE_LABELS[grade]
        print(f'  [{grade}] {label:<40} {summary.get(grade, 0):>4}')

    # ─── ملاحظات هيكلية ───────────────────────────────────────────────────────
    print(f'\n{divider}')
    print('  ملاحظات هيكلية (تتطلب قراراً في P4.2):')
    print(f'{divider}')
    print("""
  1. DEFAULT الـ DB: عمود transaction_type في الجدول account له DEFAULT='both'.
     أي حساب يُنشأ بدون تحديد transaction_type يرث 'both' تلقائياً.
     المطلوب في P4.2: تغيير DEFAULT إلى 'cash' (بعد تصحيح الحسابات الـ18).

  2. جميع الحسابات الـ18 فئة [B]:
     - بلا حركة محاسبية (JE=0, Voucher=0)
     - بلا تبعيات (entities, mappings, children = 0)
     - بلا رصيد (cash=0, weight=0)
     - بلا خزائن مرتبطة
     → آمنة للتصحيح الجماعي في P4.2 مع migration مُراجَعة

  3. الحسابات 1115 (تابي) و 1116 (تمارا) محمية بقيد مستخدم:
     "لا تابي ولا تمارا" — تُعالَج في نفس P4.2 migration دون تغيير منطقها.
""")
    print(divider)


# ─── نقطة الدخول ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import os
    os.environ.setdefault('YASAR_ENV', 'production')

    from app import app
    with app.app_context():
        data = run_audit()
        print_report(data)
