"""
fix_production_je.py
====================
سكريبت لتشخيص وإصلاح القيود المرحّلة بشكل مزدوج في الإنتاج.

المشكلة:
  - قيود JournalEntry ذات reference_type='invoice' تم ترحيلها بشكل مستقل
    عبر "ترحيل الكل" في شاشة القيود، مما أدى لازدواجية في رصيد الخزائن.

منطق الإصلاح:
  - القيد مرتبط بفاتورة مرحّلة   → يُبقى مرحّلاً (صحيح)
  - القيد مرتبط بفاتورة غير مرحّلة → يُلغى ترحيله (خطأ حدث سابقاً)
  - القيد مرتبط بفاتورة غير موجودة → يُلغى ترحيله للأمان

تشغيل التشخيص:
  python fix_production_je.py --dry-run

تطبيق الإصلاح:
  python fix_production_je.py --apply
"""
import os
import sys
import argparse
from datetime import datetime

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--apply', action='store_true')
parser.add_argument('--db-url', default=None, help='PostgreSQL DATABASE_URL للإنتاج')
parser.add_argument('-h', '--help', action='store_true')
_pre_args, _ = parser.parse_known_args()

if _pre_args.help:
    print(__doc__)
    sys.exit(0)

if _pre_args.db_url:
    os.environ['DATABASE_URL'] = _pre_args.db_url

os.environ.setdefault('FLASK_ENV', 'production')

from app import app
from models import db, JournalEntry, JournalEntryLine, Invoice, SafeBoxTransaction, AuditLog


def diagnose(apply=False):
    with app.app_context():
        mode = "APPLY" if apply else "DRY-RUN"
        print(f"\n{'='*60}")
        print(f"  {mode} - إصلاح القيود المرحّلة المرتبطة بفواتير")
        print(f"{'='*60}\n")

        # --------- 1. جميع القيود المرتبطة بفواتير والمرحّلة ---------
        je_linked = JournalEntry.query.filter(
            JournalEntry.reference_type == 'invoice',
            JournalEntry.is_posted == True,
            JournalEntry.is_deleted == False,
        ).all()

        print(f"جميع القيود المرتبطة بفواتير والمرحّلة: {len(je_linked)}\n")

        to_unpost = []   # قيود يجب إلغاء ترحيلها
        already_ok = []  # قيود صحيحة (فاتورتها مرحّلة)

        for je in je_linked:
            inv = Invoice.query.get(je.reference_id) if je.reference_id else None
            if inv is None or not inv.is_posted:
                to_unpost.append((je, inv))
            else:
                already_ok.append((je, inv))

        print(f"✅ قيود صحيحة (فاتورتها مرحّلة): {len(already_ok)}")
        print(f"⚠️  قيود تحتاج إلغاء ترحيل:       {len(to_unpost)}\n")

        # --------- 2. فحص ازدواجية SafeBoxTransaction ---------
        print("--- فحص SafeBoxTransaction (عينة من الصحيحة) ---")
        duplicated_safe_txs = []
        for je, inv in already_ok[:30]:
            # نحسب: هل الخزينة فيها إدخال مكرر?
            # مؤشر الازدواجية: invoice_payment + gold_reversal غير موجودة
            pay_txs = SafeBoxTransaction.query.filter_by(
                invoice_id=inv.id, ref_type='invoice_payment'
            ).count()
            gold_txs = SafeBoxTransaction.query.filter_by(
                invoice_id=inv.id, ref_type='invoice_gold'
            ).count()
            gold_rev = SafeBoxTransaction.query.filter_by(
                invoice_id=inv.id, ref_type='invoice_gold_reversal'
            ).count()
            flag = ""
            if pay_txs > 1:
                flag = " ⚠️  pay_txs مكررة!"
                duplicated_safe_txs.append(inv.id)
            print(f"  فاتورة #{inv.id} ({inv.invoice_type}) | "
                  f"je#{je.id} | pay_txs={pay_txs} gold_txs={gold_txs} gold_rev={gold_rev}{flag}")

        if duplicated_safe_txs:
            print(f"\n⚠️  فواتير بـ SafeBoxTransaction مكررة: {duplicated_safe_txs}")
        else:
            print("\n✅ لا توجد ازدواجية في SafeBoxTransaction")

        # --------- 3. تفاصيل القيود التي ستُصلح ---------
        if to_unpost:
            print(f"\n--- قيود سيُلغى ترحيلها ({len(to_unpost)}) ---")
            for je, inv in to_unpost[:50]:
                inv_info = f"فاتورة #{inv.id} ({inv.invoice_type}) غير مرحّلة" if inv else "فاتورة غير موجودة"
                print(f"  JE#{je.id} ({je.entry_number or '-'}) | {inv_info} | {je.description or ''}")

        print(f"\n{'='*60}")

        if not apply:
            print("  هذا DRY-RUN فقط - لم يتغير شيء.")
            print("  لتطبيق الإصلاح: python fix_production_je.py --apply")
            print(f"{'='*60}\n")
            return

        # --------- 4. تطبيق الإصلاح ---------
        if not to_unpost:
            print("  لا يوجد شيء يحتاج إصلاح.")
            print(f"{'='*60}\n")
            return

        print("\n  تطبيق الإصلاح...")
        fixed = 0
        for je, inv in to_unpost:
            je.is_posted = False
            je.posted_at = None
            je.posted_by = None
            fixed += 1

        try:
            db.session.commit()
            print(f"\n  ✅ تم إلغاء ترحيل {fixed} قيد بنجاح.")
            try:
                AuditLog.log_action(
                    user_name='system_fix',
                    action='bulk_unpost_invoice_linked_jes',
                    entity_type='JournalEntry',
                    entity_id=0,
                    details=f'Fixed {fixed} invoice-linked JEs incorrectly posted independently',
                    success=True,
                )
                db.session.commit()
            except Exception:
                pass
        except Exception as e:
            db.session.rollback()
            print(f"\n  ❌ خطأ: {e}")

        print(f"{'='*60}\n")


if __name__ == '__main__':
    diagnose(apply=_pre_args.apply)
