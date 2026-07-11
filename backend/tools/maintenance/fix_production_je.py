"""
fix_production_je.py
====================
سكريبت لتشخيص وإصلاح مشكلتين في الإنتاج:

المشكلة 1 (القديمة):
  - قيود reference_type='invoice' تم ترحيلها بشكل مستقل عبر "ترحيل الكل"
    بينما فاتورتها غير مرحّلة → يُلغى ترحيلها.

المشكلة 2 (ازدواجية الخزينة):
  - عند الاستيراد من Excel (force_post)، يُنشأ:
      أ) قيد الفاتورة (reference_type='invoice'): يُمدن حساب الخزينة
      ب) قيد السند (reference_type='voucher'): يُمدن نفس الخزينة
  - النتيجة: رصيد الخزينة مضاعف في كشف الحساب.
  - الإصلاح: في قيد الفاتورة، نحوّل سطور مدين الخزينة إلى مدين حساب العميل/المورد.

الاستخدام:
  python fix_production_je.py                         ← تشخيص فقط (dry-run)
  python fix_production_je.py --apply                 ← تطبيق الإصلاح
  python fix_production_je.py --db-url "postgresql://..."   ← الاتصال بقاعدة بيانات خارجية
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
from models import (
    db, JournalEntry, JournalEntryLine, Invoice, SafeBoxTransaction,
    AuditLog, SafeBox, Account, Customer, Supplier,
)

try:
    from models import Voucher
except ImportError:
    Voucher = None


# ──────────────────────────────────────────────────────────────────────────────
def _safe_account_ids():
    try:
        safes = SafeBox.query.filter(SafeBox.account_id.isnot(None)).all()
        return {int(s.account_id) for s in safes if s.account_id}
    except Exception:
        return set()


def _party_account_id(inv):
    try:
        if getattr(inv, 'customer_id', None):
            c = Customer.query.get(inv.customer_id)
            return int(c.account_id) if (c and c.account_id) else None
        if getattr(inv, 'supplier_id', None):
            s = Supplier.query.get(inv.supplier_id)
            return int(s.account_id) if (s and s.account_id) else None
    except Exception:
        pass
    return None


def _check1_unposted():
    jes = JournalEntry.query.filter(
        JournalEntry.reference_type == 'invoice',
        JournalEntry.is_posted == True,
        JournalEntry.is_deleted == False,
    ).all()
    ok, bad = [], []
    for je in jes:
        inv = Invoice.query.get(je.reference_id) if je.reference_id else None
        (ok if (inv and inv.is_posted) else bad).append((je, inv))
    return ok, bad


def _check2_double_safe(already_ok, safe_ids):
    if not safe_ids or Voucher is None:
        if Voucher is None:
            print("  ⚠️  نموذج Voucher غير موجود - تخطي الفحص 2")
        return []
    issues = []
    for je, inv in already_ok:
        has_voucher = Voucher.query.filter_by(
            reference_type='invoice', reference_id=inv.id
        ).first() is not None
        if not has_voucher:
            continue
        safe_lines = JournalEntryLine.query.filter(
            JournalEntryLine.journal_entry_id == je.id,
            JournalEntryLine.account_id.in_(safe_ids),
            JournalEntryLine.cash_debit > 0,
        ).all()
        if safe_lines:
            issues.append((je, inv, safe_lines, _party_account_id(inv)))
    return issues


# ──────────────────────────────────────────────────────────────────────────────
def diagnose(apply=False):
    with app.app_context():
        mode = "APPLY" if apply else "DRY-RUN"
        print(f"\n{'='*60}")
        print(f"  {mode} - إصلاح المشاكل المحاسبية في الإنتاج")
        print(f"{'='*60}\n")

        safe_ids = _safe_account_ids()
        print(f"  حسابات الخزائن: {sorted(safe_ids) or 'لا يوجد'}\n")

        # ── الفحص 1 ──────────────────────────────────────────────────────────
        print("━━ الفحص 1: قيود مرحّلة لفواتير غير مرحّلة ━━")
        already_ok, to_unpost = _check1_unposted()
        print(f"  ✅ قيود صحيحة:             {len(already_ok)}")
        print(f"  ⚠️  تحتاج إلغاء ترحيل:    {len(to_unpost)}")
        for je, inv in to_unpost[:20]:
            label = f"فاتورة #{inv.id} ({inv.invoice_type})" if inv else "فاتورة مفقودة"
            print(f"      JE#{je.id} | {label}")

        # ── الفحص 2 ──────────────────────────────────────────────────────────
        print("\n━━ الفحص 2: ازدواجية مدين الخزينة (فاتورة + سند) ━━")
        double_issues = _check2_double_safe(already_ok, safe_ids)
        print(f"  ⚠️  فواتير بازدواجية خزينة: {len(double_issues)}")
        for je, inv, lines, party_id in double_issues[:30]:
            dup_total = sum(float(ln.cash_debit or 0) for ln in lines)
            party_info = f"→ حساب طرف #{party_id}" if party_id else "⚠️  لا حساب طرف"
            print(f"      JE#{je.id} | فاتورة #{inv.id} ({inv.invoice_type}) | "
                  f"مدين مكرر={dup_total:.2f} | {party_info}")

        # ── الملخص ───────────────────────────────────────────────────────────
        total = len(to_unpost) + len(double_issues)
        print(f"\n{'='*60}")
        print(f"  إجمالي العمليات المطلوبة: {total}")

        if not apply:
            print("  هذا DRY-RUN فقط - لم يتغير شيء.")
            print("  لتطبيق الإصلاح: python fix_production_je.py --apply")
            print(f"{'='*60}\n")
            return

        if total == 0:
            print("  لا يوجد شيء يحتاج إصلاح.")
            print(f"{'='*60}\n")
            return

        print("\n  تطبيق الإصلاح...")
        f1 = f2 = 0

        for je, inv in to_unpost:
            je.is_posted = False
            je.posted_at = None
            je.posted_by = None
            f1 += 1

        for je, inv, lines, party_id in double_issues:
            if not party_id:
                print(f"  ⚠️  تخطي JE#{je.id}: لا حساب طرف لفاتورة #{inv.id}")
                continue
            for ln in lines:
                old = ln.account_id
                ln.account_id = party_id
                print(f"  ✏️  JE#{je.id} Line#{ln.id}: حساب {old}→{party_id} "
                      f"مدين={float(ln.cash_debit or 0):.2f}")
            f2 += 1

        try:
            db.session.commit()
            print(f"\n  ✅ الفحص 1: أُلغي ترحيل {f1} قيد.")
            print(f"  ✅ الفحص 2: أُصلح {f2} قيد فاتورة (مدين الخزينة → ذمم الطرف).")
            try:
                AuditLog.log_action(
                    user_name='system_fix',
                    action='fix_production_double_safe',
                    entity_type='JournalEntry',
                    entity_id=0,
                    details=f'check1={f1}, check2={f2}',
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
