"""
verify_clearing_guard_live.py
================================
تحقّق مباشر (لا افتراض) من أن حارس "تصنيف القيود على حسابات المقاصة"
(المُضاف في models.py عبر before_insert/before_update على JournalEntryLine)
فعّال حقيقةً على هذا الكود المنشور.

يحاول إنشاء JournalEntryLine على أول حساب مقاصة (safe_type='clearing')
بدون reference_type على القيد الأب — يجب أن يُرفَض (ValueError). ثم يتأكد
أن قيداً مصنَّفاً بشكل صحيح (reference_type='clearing_settlement') يُقبَل
بلا مشاكل. كل شيء داخل rollback كامل — لا يُحفظ أي شيء أبداً، بصرف النظر
عن نتيجة الاختبار.

تشغيل:
    docker cp backend/verify_clearing_guard_live.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/verify_clearing_guard_live.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, JournalEntry, JournalEntryLine, SafeBox


def run():
    with app.app_context():
        try:
            clearing_sb = SafeBox.query.filter_by(safe_type='clearing').first()
            if not clearing_sb:
                print("❌ لا يوجد أي صندوق safe_type='clearing' في هذه القاعدة — لا يمكن إجراء الاختبار.")
                return
            account_id = clearing_sb.account_id
            print(f"يُختبَر على: {clearing_sb.name} (safe_box_id={clearing_sb.id}, account_id={account_id})")

            # --- Test 1: unclassified entry on the clearing account must be rejected ---
            je1 = JournalEntry(
                entry_number='VERIFY-GUARD-1', date=db.func.now(),
                description='verify_clearing_guard_live test', reference_type=None, created_by='verify_script',
            )
            db.session.add(je1)
            db.session.flush()
            line1 = JournalEntryLine(
                journal_entry_id=je1.id, account_id=account_id,
                cash_debit=1.0, cash_credit=0.0, description='test',
            )
            db.session.add(line1)
            try:
                db.session.flush()
                print("❌ FAILED: توقّعنا ValueError ولم يُرفَع أي خطأ — الحارس غير فعّال على هذا الكود المنشور.")
                db.session.rollback()
                return
            except ValueError as exc:
                print("✅ Test 1 PASSED: قيد غير مصنَّف على حساب مقاصة رُفض فعلياً:", str(exc)[:120])
            db.session.rollback()

            # --- Test 2: a properly classified clearing_settlement entry must be allowed ---
            je2 = JournalEntry(
                entry_number='VERIFY-GUARD-2', date=db.func.now(),
                description='verify_clearing_guard_live test', reference_type='clearing_settlement',
                created_by='verify_script',
            )
            db.session.add(je2)
            db.session.flush()
            line2 = JournalEntryLine(
                journal_entry_id=je2.id, account_id=account_id,
                cash_debit=1.0, cash_credit=0.0, description='test',
            )
            db.session.add(line2)
            db.session.flush()
            print("✅ Test 2 PASSED: قيد مصنَّف (clearing_settlement) على حساب مقاصة سُمح به بلا مشاكل.")

            print("\n✅✅ الحارس فعّال على هذا الكود المنشور فعلياً، ولا يكسر المسار الشرعي.")
        finally:
            db.session.rollback()
            leftover = JournalEntry.query.filter(
                JournalEntry.entry_number.in_(['VERIFY-GUARD-1', 'VERIFY-GUARD-2'])
            ).count()
            print(f"(تراجع كامل — لا أثر متبقٍ: {leftover} سجل)")


if __name__ == '__main__':
    run()
