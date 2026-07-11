"""
fix_type_mismatch_pairs.py
=============================
يصحّح الحالات الثلاث الأخيرة المتبقية من audit_account_memo_invariants.py
(type_mismatch) -- آخر عائق أمام Protection level: FULL الكامل بلا أي
استثناء معروف.

السياق: كل زوج من الثلاثة (914/915، 763/764، 765/766) كلا حسابيه
tracks_weight=True حالياً، رغم أن أحدهما يجب أن يكون مالياً (False) بحكم
استخدامه التاريخي الفعلي في دفتر الأستاذ -- لا تخمين من الاسم أو رقم
الحساب، بل من فحص diagnose_type_mismatch_pairs.py لكل حساب:

  - #914 "مصروفات أجور المصنعية": 909 سطراً، 405,936.22 نقدي، صفر وزني.
  - #763 "مخزون أجور المصنعية": 1014 سطراً، 785,782.90 نقدي، صفر وزني.
  - #765 "صندوق الكسر الرئيسي": صفر سطور له مباشرة، لكن شريكه #766 له 285
    سطراً وزنياً مؤكَّداً (33,315.051 جم) -- فـ765 هو المالي بالاستثناء.

(الأرقام 7xxx لشركائها -915/764/766- تتفق مع هذا الاستنتاج، لكنها مؤكِّدة
لا مصدر القرار -- المصدر هو الاستخدام الفعلي في القيود).

الإصلاح:
  1. تعيين tracks_weight=False على 914، 763، 765 (الثلاثة فقط -- لا لمس
     915/764/766، صحيحة تماماً كما هي).
  2. لكل زوج: استدعاء account_pair_service.link_accounts() لإنشاء الربط
     الثنائي الصحيح بينهما (لم يكن ممكناً قبل هذا التصحيح -- الخدمة ترفض
     ربط حسابين من نفس tracks_weight).

بعد هذا السكريبت، تشغيل audit_account_memo_invariants.py يجب أن يُظهر
صفراً في القواعد الخمس جميعها، بلا أي استثناء متبقٍّ.

الوضع الافتراضي: DRY RUN. --apply للتنفيذ الفعلي.

تشغيل:
    docker exec yasargold-backend python backend/fix_type_mismatch_pairs.py            # dry run
    docker exec yasargold-backend python backend/fix_type_mismatch_pairs.py --apply    # تنفيذ فعلي
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, Account
from account_pair_service import link_accounts, AccountPairLinkError

FIXES = [
    (914, 915, 'مصروفات أجور المصنعية'),
    (763, 764, 'مخزون أجور المصنعية'),
    (765, 766, 'صندوق الكسر الرئيسي'),
]


def run(apply: bool) -> int:
    with app.app_context():
        print(f"{'='*60}")
        print(f"{'تطبيق فعلي' if apply else 'DRY RUN -- لا كتابة'}")
        print(f"{'='*60}")

        plan = []
        for financial_id, weight_id, label in FIXES:
            financial = Account.query.get(financial_id)
            weight = Account.query.get(weight_id)
            if not financial or not weight:
                print(f"❌ {label}: أحد الحسابين (#{financial_id}/#{weight_id}) غير موجود -- تخطّي.")
                continue

            print(f"\n{label}: #{financial.id} <-> #{weight.id}")
            print(f"  #{financial.id} tracks_weight: {financial.tracks_weight} -> False")
            print(f"  #{weight.id} tracks_weight: {weight.tracks_weight} (بلا تغيير)")
            print(f"  ثم: link_accounts(#{financial.id}, #{weight.id})")
            plan.append((financial, weight))

        if not apply:
            print("\n(DRY RUN) لتطبيق التغيير فعليًا أضف --apply")
            return 0

        errors = []
        for financial, weight in plan:
            financial.tracks_weight = False
            db.session.add(financial)
            db.session.flush()
            try:
                link_accounts(financial, weight, created_by='fix_type_mismatch_pairs')
            except AccountPairLinkError as exc:
                errors.append((financial, weight, str(exc)))

        if errors:
            db.session.rollback()
            print(f"\n❌ فشل الربط لـ{len(errors)} زوج، أُلغي كل شيء:")
            for financial, weight, reason in errors:
                print(f"   #{financial.id}/#{weight.id}: {reason}")
            return 1

        db.session.commit()
        print(f"\n✅ تم تصحيح وربط {len(plan)} زوج بنجاح.")
        return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    sys.exit(run(apply=args.apply))
