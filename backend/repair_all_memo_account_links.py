"""
repair_all_memo_account_links.py
===================================
أداة صيانة دائمة وحيدة لمشاكل ربط memo_account_id -- تحل محل تراكم
سكربتات إصلاح مخصصة لكل حادثة (fix_office_memo_account_link.py،
repair_memo_accounts.py، وجزء الربط من fix_office6_weight_account_1213_to_1074.py
-- تصحيح سطر JE#4709 نفسه يبقى خاصاً بتلك الحادثة، فهذا ليس مشكلة ربط حسابات).

idempotent بالكامل: لا منطق إصلاح هنا على الإطلاق -- فقط يكتشف الحالات
(بنفس قواعد audit_account_memo_invariants.py الخمس) ويستدعي
account_pair_service لكل حالة *لا غموض فيها*. أي تحسين مستقبلي على قواعد
الخدمة يستفيد منه هذا السكربت تلقائياً دون أي تعديل هنا.

يُصلَح تلقائياً (بلا حاجة لحكم بشري):
  - self_reference: فسخ الربط (unlink_account).
  - one_way_link حيث الطرف الآخر None فعلاً (ربط غير مكتمل، لا تعارض):
    إكماله عبر link_accounts().

يُترَك للمراجعة البشرية دائماً (يحتاج تحقيقاً كحادثة #1213 التي احتاجت
فحص أرصدة دفتر الأستاذ لمعرفة أي حساب يحوي البيانات الحقيقية):
  - broken_reference (لا توجد طريقة لمعرفة الهدف الصحيح).
  - one_way_link حيث الطرف الآخر يشير لحساب ثالث (تعارض حقيقي).
  - duplicate_target (أي الحسابين المتنازعين يحوي البيانات الحقيقية؟).
  - type_mismatch (أي الحسابين من النوع الخطأ؟).
  - أي حالة يرفضها account_pair_service فعلياً (مثل: حساب هدف موسوم متروك
    -- هذا تحديداً ما يحمي من تكرار حادثة #1213 لو حاول هذا السكربت
    "إكمال" ربط #1072 بـ#1213 تلقائياً: الخدمة ترفضه، فيصبح "يحتاج مراجعة"
    بدل أن يُصلَح للحساب الخطأ بصمت).

الوضع الافتراضي: DRY RUN (لا كتابة، يطبع فقط ما سيحدث). --apply للتنفيذ.

تشغيل:
    docker cp backend/repair_all_memo_account_links.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/repair_all_memo_account_links.py            # dry run
    docker exec yasargold-backend python backend/repair_all_memo_account_links.py --apply    # تنفيذ فعلي
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, Account
from account_pair_service import link_accounts, unlink_account, AccountPairLinkError


def _is_deprecated(acc: Account) -> bool:
    return bool(acc.name) and any(m in acc.name for m in Account._DEPRECATED_ACCOUNT_MARKERS)


def _label(acc) -> str:
    return f"#{acc.id} {acc.name}" if acc else '(-)'


def run(apply: bool) -> int:
    with app.app_context():
        all_accounts = Account.query.all()
        by_id = {a.id: a for a in all_accounts}
        linked = [a for a in all_accounts if a.memo_account_id is not None]

        checked = 0
        already_correct = 0
        auto_fixable_self_ref = []
        auto_fixable_one_way = []
        needs_review = []
        seen_pairs = set()

        for a in linked:
            checked += 1
            target = by_id.get(a.memo_account_id)

            if target is None:
                needs_review.append((a, None, 'broken_reference: الهدف غير موجود'))
                continue

            if target.id == a.id:
                auto_fixable_self_ref.append(a)
                continue

            pair_key = frozenset({a.id, target.id})
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            if target.memo_account_id == a.id:
                if bool(target.tracks_weight) == bool(a.tracks_weight):
                    needs_review.append((a, target, 'type_mismatch: كلا الحسابين بنفس tracks_weight'))
                else:
                    already_correct += 1
                continue

            if target.memo_account_id is not None:
                needs_review.append((
                    a, target,
                    f'one_way_link متعارض: {target.id}.memo_account_id={target.memo_account_id} (ليس {a.id})'
                ))
                continue

            # one-way, target.memo_account_id is None -- auto-fixable IF لا أحد طرفيه متروك.
            if _is_deprecated(a) or _is_deprecated(target):
                needs_review.append((a, target, 'one_way_link غير قابل للإكمال تلقائياً: أحد الطرفين موسوم متروك'))
                continue
            if bool(target.tracks_weight) == bool(a.tracks_weight):
                needs_review.append((a, target, 'type_mismatch: كلا الحسابين بنفس tracks_weight'))
                continue

            auto_fixable_one_way.append((a, target))

        # duplicate_target: عدة حسابات (مختلفة) تشير لنفس الهدف -- يحتاج مراجعة دائماً.
        targets_count: dict = {}
        for a in linked:
            targets_count.setdefault(a.memo_account_id, []).append(a)
        for target_id, pointers in targets_count.items():
            if len(pointers) > 1:
                target = by_id.get(target_id)
                needs_review.append((
                    None, target,
                    f'duplicate_target: ' + ', '.join(_label(p) for p in pointers) + f' كلهم يشيرون لـ{_label(target)}'
                ))

        fixed = 0
        errors = []

        if apply:
            for a in auto_fixable_self_ref:
                try:
                    unlink_account(a, created_by='repair_all_memo_account_links')
                    fixed += 1
                except Exception as exc:
                    errors.append((a, None, f'فشل فسخ self_reference: {exc}'))

            for a, target in auto_fixable_one_way:
                try:
                    link_accounts(a, target, created_by='repair_all_memo_account_links')
                    fixed += 1
                except AccountPairLinkError as exc:
                    needs_review.append((a, target, f'رفضته الخدمة عند التنفيذ: {exc}'))
                except Exception as exc:
                    errors.append((a, target, f'خطأ غير متوقَّع: {exc}'))

            db.session.commit()
        else:
            fixed = len(auto_fixable_self_ref) + len(auto_fixable_one_way)
            db.session.rollback()

        print(f"{'='*60}")
        print(f"{'تطبيق فعلي' if apply else 'DRY RUN -- لا كتابة'}")
        print(f"{'='*60}")
        print(f"Checked: {checked}")
        print(f"Already correct: {already_correct}")
        print(f"Fixed: {fixed}")
        print(f"Needs review: {len(needs_review)}")
        print(f"Errors: {len(errors)}")

        if not apply and (auto_fixable_self_ref or auto_fixable_one_way):
            print(f"\n--- سيُصلَح تلقائياً لو طُبِّق --apply ({fixed}) ---")
            for a in auto_fixable_self_ref:
                print(f"  {_label(a)}: فسخ self_reference")
            for a, target in auto_fixable_one_way:
                print(f"  {_label(a)} <-> {_label(target)}: إكمال ربط ثنائي")

        if needs_review:
            print(f"\n--- يحتاج مراجعة بشرية ({len(needs_review)}) ---")
            for a, target, reason in needs_review:
                print(f"  {_label(a)} <-> {_label(target)}: {reason}")

        if errors:
            print(f"\n--- أخطاء ({len(errors)}) ---")
            for a, target, reason in errors:
                print(f"  {_label(a)} <-> {_label(target)}: {reason}")

        if not apply:
            print("\n(DRY RUN) لتطبيق التغيير فعليًا أضف --apply")

        return 0 if (not needs_review and not errors) else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    sys.exit(run(apply=args.apply))
