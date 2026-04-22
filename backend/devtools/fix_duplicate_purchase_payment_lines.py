"""
إزالة سطور الدفع النقدي المكررة من قيود فواتير الشراء (مورد).

المشكلة:
  كان قيد الفاتورة (reference_type='invoice') يحتوي على سطور:
    - دائن خزينة  (safe_acc) بوصف "سداد نقدي للمورد - شراء"
    - مدين مورد   (supplier_fin) بنفس الوصف
  وهذه السطور نفسها موجودة في قيد السند (reference_type='voucher' / 'invoice_payments').

الحل:
  حذف هذه السطور من قيود الفواتير فقط (تبقى في قيود السندات).

الاستخدام:
  # عرض ما سيُحذف فقط (dry run):
  python devtools/fix_duplicate_purchase_payment_lines.py

  # تطبيق الحذف:
  python devtools/fix_duplicate_purchase_payment_lines.py --apply
"""

from __future__ import annotations

import argparse
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from app import app
from models import db, Invoice, JournalEntry, JournalEntryLine


DUPLICATE_DESCS = {
    'سداد نقدي للمورد - شراء',
    'استرداد نقدي من المورد - شراء',
}

PURCHASE_TYPES = {'شراء', 'مرتجع شراء (مورد)'}


def main(apply: bool) -> None:
    with app.app_context():
        # جلب قيود مرتبطة بفواتير شراء من مورد
        invoice_jes = (
            JournalEntry.query
            .filter(
                JournalEntry.reference_type == 'invoice',
                JournalEntry.is_deleted == False,
            )
            .all()
        )

        # فلترة على فواتير الشراء فقط
        purchase_invoice_ids = set(
            inv.id
            for inv in Invoice.query.filter(
                Invoice.invoice_type.in_(list(PURCHASE_TYPES))
            ).all()
        )

        total_lines = 0
        affected_jes = 0

        for je in invoice_jes:
            if je.reference_id not in purchase_invoice_ids:
                continue

            dup_lines = [
                ln for ln in je.lines
                if not ln.is_deleted
                and (ln.description or '').strip() in DUPLICATE_DESCS
            ]

            if not dup_lines:
                continue

            affected_jes += 1
            total_lines += len(dup_lines)

            print(f"\nJE #{je.id}  {je.entry_number}  (فاتورة #{je.reference_id})")
            for ln in dup_lines:
                print(
                    f"  سطر #{ln.id} | حساب={ln.account_id} "
                    f"| مدين={ln.cash_debit or 0:.2f}  دائن={ln.cash_credit or 0:.2f} "
                    f"| {ln.description}"
                )
                if apply:
                    ln.is_deleted = True

        print(f"\n{'=' * 60}")
        print(f"إجمالي السطور المكررة: {total_lines}  |  في {affected_jes} قيد")

        if apply:
            db.session.commit()
            print("✅ تم الحذف بنجاح.")
        else:
            print("⚠️  dry run — لم يتغير شيء. أضف --apply للتطبيق.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='تطبيق الحذف فعلياً')
    args = parser.parse_args()
    main(apply=args.apply)
