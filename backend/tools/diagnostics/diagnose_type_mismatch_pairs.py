"""
diagnose_type_mismatch_pairs.py
==================================
تشخيص فقط -- لا يكتب أي شيء.

الحالات الثلاث المتبقية من audit_account_memo_invariants.py (type_mismatch،
المتعمَّد إبقاؤها للمراجعة البشرية -- لا حل واحد صحيح يستنتجه الكود):
  #914/#915، #763/#764، #765/#766 -- كل زوج كلا حسابيه tracks_weight=True
  حالياً، رغم أن أحدهما (حسب التسمية) يُفترض أن يكون الحساب المالي
  (tracks_weight=False) والآخر الوزني.

القاعدة الموضوعية لتحديد أيهما الصحيح (لا تخمين من الاسم): أي الحسابين
استُخدم فعلياً في القيود لاستقبال مبالغ نقدية (cash_debit/cash_credit) مقابل
أوزان ذهب (debit_Xk/credit_Xk)؟ الحساب الذي له حركة نقدية فعلية هو المالي
(tracks_weight يجب أن يكون False)؛ الذي له حركة وزنية فعلية يبقى وزنياً
(tracks_weight=True يبقى صحيحاً).

هذا السكريبت يفحص فقط -- لا يُغيِّر tracks_weight لأي حساب. النتيجة تُستخدم
لتحديد التصحيح اليدوي الدقيق (سكريبت لاحق منفصل بعد المراجعة).

تشغيل (قراءة فقط):
    docker exec yasargold-backend python backend/diagnose_type_mismatch_pairs.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import Account, JournalEntryLine
from sqlalchemy import func

PAIRS = [(914, 915), (763, 764), (765, 766)]


def _activity(account_id: int) -> dict:
    row = (
        JournalEntryLine.query
        .filter(JournalEntryLine.account_id == account_id)
        .filter(JournalEntryLine.is_deleted.is_(False))
        .with_entities(
            func.coalesce(func.sum(func.abs(JournalEntryLine.cash_debit)), 0.0)
            + func.coalesce(func.sum(func.abs(JournalEntryLine.cash_credit)), 0.0),
            func.coalesce(func.sum(func.abs(JournalEntryLine.debit_18k)), 0.0)
            + func.coalesce(func.sum(func.abs(JournalEntryLine.credit_18k)), 0.0)
            + func.coalesce(func.sum(func.abs(JournalEntryLine.debit_21k)), 0.0)
            + func.coalesce(func.sum(func.abs(JournalEntryLine.credit_21k)), 0.0)
            + func.coalesce(func.sum(func.abs(JournalEntryLine.debit_22k)), 0.0)
            + func.coalesce(func.sum(func.abs(JournalEntryLine.credit_22k)), 0.0)
            + func.coalesce(func.sum(func.abs(JournalEntryLine.debit_24k)), 0.0)
            + func.coalesce(func.sum(func.abs(JournalEntryLine.credit_24k)), 0.0),
            func.count(JournalEntryLine.id),
        )
        .first()
    )
    cash_activity, weight_activity, line_count = row
    return {
        'cash_activity': float(cash_activity or 0.0),
        'weight_activity': float(weight_activity or 0.0),
        'line_count': int(line_count or 0),
    }


def run() -> None:
    with app.app_context():
        for id_a, id_b in PAIRS:
            a = Account.query.get(id_a)
            b = Account.query.get(id_b)
            if not a or not b:
                print(f"تخطّي ({id_a}, {id_b}): حساب غير موجود.")
                continue

            print(f"\n{'='*70}")
            print(f"الزوج: #{a.id} {a.name} (رقم {a.account_number}) <-> #{b.id} {b.name} (رقم {b.account_number})")

            for acc in (a, b):
                act = _activity(acc.id)
                suggestion = (
                    'مالي (tracks_weight يجب أن يكون False)' if act['cash_activity'] > 0 and act['weight_activity'] == 0
                    else 'وزني (tracks_weight=True صحيح كما هو)' if act['weight_activity'] > 0 and act['cash_activity'] == 0
                    else 'كلاهما له حركة (نقدية ووزنية معاً) -- يحتاج فحصاً يدوياً أعمق' if act['cash_activity'] > 0 and act['weight_activity'] > 0
                    else 'لا حركة إطلاقاً -- لا يوجد دليل من القيود'
                )
                print(f"  #{acc.id}: tracks_weight الحالي={acc.tracks_weight} | "
                      f"عدد السطور={act['line_count']} | "
                      f"إجمالي نقدي={act['cash_activity']:.2f} | إجمالي وزني={act['weight_activity']:.3f}")
                print(f"      الاقتراح بناءً على الاستخدام الفعلي: {suggestion}")


if __name__ == '__main__':
    run()
