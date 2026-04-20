"""
merge_cash_customers.py
=======================
دمج سجلات "عميل نقدي" المكررة في قاعدة البيانات إلى سجل واحد (canonical).

المشكلة: عند إنشاء فواتير بدون تحديد عميل، قد ينشئ النظام أو أدوات الاستيراد
سجلات "عميل نقدي" متعددة بمعرّفات مختلفة. هذا السكريبت يدمجها في عميل واحد.

الخطوات:
1. رصد جميع العملاء الذين اسمهم من قائمة أسماء العميل النقدي.
2. اختيار السجل الأول (canonical) بأقل ID ويفضّل أن يكون له account_id.
3. تحويل جميع المراجع للسجلات المكررة إلى السجل الأصلي:
   - invoice.customer_id
   - journal_entry_line.customer_id + account_id
   - voucher.customer_id
   - voucher_account_line.account_id
4. تعطيل السجلات المكررة (active=False).

الاستخدام:
    python backend/devtools/merge_cash_customers.py          # dry-run
    python backend/devtools/merge_cash_customers.py --apply  # تطبيق فعلي
"""

import sys
import os
import argparse

# ── PATH SETUP ────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, BACKEND_DIR)

from app import app  # noqa: E402
from models import db, Customer, Invoice, JournalEntryLine, Voucher  # noqa: E402
from sqlalchemy import func  # noqa: E402

# الأسماء المعروفة للعميل النقدي
CASH_CUSTOMER_ALIASES = {'عميل نقدي', 'نقدي', 'عميل كاش'}


def run(apply: bool = False) -> None:
    with app.app_context():
        # ── 1. رصد جميع السجلات ───────────────────────────────────────────
        # Use func.trim to catch names with trailing/leading whitespace
        all_cash = (
            Customer.query
            .filter(func.trim(Customer.name).in_(list(CASH_CUSTOMER_ALIASES)))
            .order_by(Customer.id.asc())
            .all()
        )

        if not all_cash:
            print("✅  لا يوجد أي عميل نقدي — لا شيء للدمج.")
            return

        print(f"🔍  وُجد {len(all_cash)} سجل(ات) للعميل النقدي:")
        for c in all_cash:
            print(f"    id={c.id:>5}  code={c.customer_code:<12}  name={c.name!r}"
                  f"  active={c.active}  account_id={c.account_id}")

        if len(all_cash) == 1:
            print("✅  سجل واحد فقط — لا حاجة للدمج.")
            return

        # ── 2. اختيار الـ canonical ────────────────────────────────────────
        # نفضّل السجل الذي لديه account_id أولاً، ثم أقل ID
        with_account = [c for c in all_cash if c.account_id is not None]
        canonical = with_account[0] if with_account else all_cash[0]
        duplicates = [c for c in all_cash if c.id != canonical.id]

        print(f"\n📌  السجل الأصلي (canonical): id={canonical.id}  name={canonical.name!r}"
              f"  account_id={canonical.account_id}")
        print(f"🗑️   السجلات المكررة ({len(duplicates)}): {[c.id for c in duplicates]}")

        dup_ids = [c.id for c in duplicates]
        # حسابات العملاء المكررة التي يجب إعادة توجيه القيود نحو حساب canonical
        dup_account_ids = [c.account_id for c in duplicates if c.account_id is not None]

        # إذا لم يكن للـ canonical حساب وللمكررات حسابات، انقل أول حساب للـ canonical
        adopted_account_id = None
        if canonical.account_id is None and dup_account_ids:
            adopted_account_id = dup_account_ids[0]
            dup_account_ids = dup_account_ids[1:]
            print(f"\n⚡  الـ canonical ليس له حساب؛ سيُعتمد account_id={adopted_account_id} من المكررات.")

        canonical_account_id = adopted_account_id or canonical.account_id

        # ── 3. إحصاء التأثيرات ────────────────────────────────────────────
        inv_count = Invoice.query.filter(Invoice.customer_id.in_(dup_ids)).count()

        jel_customer_count = (
            JournalEntryLine.query
            .filter(JournalEntryLine.customer_id.in_(dup_ids))
            .count()
        )
        jel_account_count = (
            JournalEntryLine.query
            .filter(JournalEntryLine.account_id.in_(dup_account_ids))
            .count()
        ) if dup_account_ids else 0

        voucher_count = Voucher.query.filter(Voucher.customer_id.in_(dup_ids)).count()

        val_count = 0
        if dup_account_ids:
            placeholders = ','.join(str(int(i)) for i in dup_account_ids)
            row = db.session.execute(
                db.text(f"SELECT COUNT(*) FROM voucher_account_line WHERE account_id IN ({placeholders})")
            ).fetchone()
            val_count = row[0] if row else 0

        print(f"\n📊  تأثير الدمج:")
        print(f"    invoice.customer_id             : {inv_count} صف")
        print(f"    journal_entry_line.customer_id  : {jel_customer_count} صف")
        print(f"    journal_entry_line.account_id   : {jel_account_count} صف  "
              f"(حسابات مكررة: {dup_account_ids})")
        print(f"    voucher.customer_id             : {voucher_count} صف")
        print(f"    voucher_account_line.account_id : {val_count} صف")

        if not apply:
            print("\n⚠️   وضع DRY-RUN — لم يتم تطبيق أي تغيير.")
            print("     أضف --apply لتطبيق الدمج فعلياً.")
            return

        # ── 4. تطبيق التغييرات ────────────────────────────────────────────
        print("\n🔧  جاري التطبيق...")

        # 4a. Invoice.customer_id
        if inv_count:
            (
                Invoice.query
                .filter(Invoice.customer_id.in_(dup_ids))
                .update({Invoice.customer_id: canonical.id}, synchronize_session='fetch')
            )
            print(f"    ✓ تحديث {inv_count} فاتورة → customer_id={canonical.id}")

        # 4b. JournalEntryLine.customer_id
        if jel_customer_count:
            (
                JournalEntryLine.query
                .filter(JournalEntryLine.customer_id.in_(dup_ids))
                .update({JournalEntryLine.customer_id: canonical.id}, synchronize_session='fetch')
            )
            print(f"    ✓ تحديث {jel_customer_count} سطر قيد → customer_id={canonical.id}")

        # 4c. JournalEntryLine.account_id
        if jel_account_count and canonical_account_id:
            (
                JournalEntryLine.query
                .filter(JournalEntryLine.account_id.in_(dup_account_ids))
                .update({JournalEntryLine.account_id: canonical_account_id}, synchronize_session='fetch')
            )
            print(f"    ✓ تحديث {jel_account_count} سطر قيد → account_id={canonical_account_id}")

        # 4d. Voucher.customer_id
        if voucher_count:
            (
                Voucher.query
                .filter(Voucher.customer_id.in_(dup_ids))
                .update({Voucher.customer_id: canonical.id}, synchronize_session='fetch')
            )
            print(f"    ✓ تحديث {voucher_count} سند → customer_id={canonical.id}")

        # 4e. VoucherAccountLine.account_id — raw SQL
        if val_count and canonical_account_id and dup_account_ids:
            placeholders = ','.join(str(int(i)) for i in dup_account_ids)
            db.session.execute(
                db.text(
                    f"UPDATE voucher_account_line SET account_id = :aid "
                    f"WHERE account_id IN ({placeholders})"
                ),
                {"aid": canonical_account_id},
            )
            print(f"    ✓ تحديث {val_count} سطر سند → account_id={canonical_account_id}")

        # 4f. اعتماد الحساب على canonical إذا كان مستعاراً
        if adopted_account_id is not None:
            canonical.account_id = adopted_account_id
            for dup in duplicates:
                if dup.account_id == adopted_account_id:
                    dup.account_id = None

        # 4g. تعطيل السجلات المكررة
        for dup in duplicates:
            dup.active = False
            dup.account_id = None  # فكّ الربط لتجنب تعارض الحسابات

        db.session.commit()
        print(f"    ✓ تعطيل {len(duplicates)} سجل(ات) مكررة (active=False)")
        print(f"\n✅  تم الدمج بنجاح!")
        print(f"    العميل النقدي الأصلي: id={canonical.id}  "
              f"code={canonical.customer_code}  account_id={canonical.account_id}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='دمج سجلات العميل النقدي المكررة')
    parser.add_argument(
        '--apply', action='store_true',
        help='تطبيق التغييرات فعلياً (الافتراضي: dry-run)'
    )
    args = parser.parse_args()
    run(apply=args.apply)
