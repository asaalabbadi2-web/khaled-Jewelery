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

ثلاث مراحل واضحة لكل تشغيل:
  1. Audit  -- تصنيف كل حساب مرتبط حسب القواعد الخمس.
  2. Plan   -- تقرير AUTO-FIX (ثقة HIGH دائماً بالتصميم -- أي حالة أقل
     يقيناً تُوجَّه لـMANUAL REVIEW منذ التصنيف، فلا تدرّج ثقة داخل قائمة
     الإصلاح نفسها) وMANUAL REVIEW (HIGH/MANUAL) مع السبب والإجراء لكل حساب.
  3. Verify -- يطبّق كل إصلاحات AUTO-FIX فعلياً في الذاكرة (flush بلا commit)،
     يُعيد تصنيف الحالة الناتجة، ويتأكد أنها أصبحت بالضبط كما يجب
     (broken_reference=self_reference=one_way_link=duplicate_target=0،
     وlen(needs_review) لم يتغيّر إلا بطرح ما أُصلح -- أي لا مخالفة جديدة
     ظهرت). فقط لو تطابقت المعاينة مع المتوقَّع: يُسمَح بـcommit الفعلي (لو
     --apply)، وإلا يُرفض التنفيذ بالكامل (rollback، خروج بحالة خطأ) --
     حتى لو طُلب --apply صريحاً.

يُصلَح تلقائياً (بلا حاجة لحكم بشري -- كل حالة هنا لها تفسير صحيح واحد فقط):
  - self_reference: فسخ الربط (unlink_account).
  - one_way_link حيث الطرف الآخر None فعلاً (ربط غير مكتمل، لا تعارض):
    إكماله عبر link_accounts().
  - duplicate_target حيث أحد المتنازعين (أو أكثر) موسوم متروك صريحاً، ولا
    يوجد أكثر من منازع واحد غير متروك: فسخ ربط الحساب(ات) المتروكة فقط.

يُترَك للمراجعة البشرية دائماً: broken_reference، one_way_link متعارض
(الطرف الآخر يشير لحساب ثالث)، duplicate_target بدون حل واضح، type_mismatch،
وأي حالة يرفضها account_pair_service فعلياً (مثل: حساب هدف موسوم متروك).

الوضع الافتراضي: DRY RUN (لا كتابة، يطبع فقط ما سيحدث، ويُجري المعاينة
للتأكد من النتيجة دون commit). --apply يكتب فعلياً، وفقط لو نجحت المعاينة.

تشغيل:
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

ISSUE_LABELS = {
    'self_reference': 'self_reference',
    'one_way_link_clean': 'one_way_link',
    'one_way_link_conflict': 'one_way_link',
    'duplicate_target_resolved': 'duplicate_target',
    'duplicate_target_conflict': 'duplicate_target',
    'broken_reference': 'broken_reference',
    'type_mismatch': 'type_mismatch',
}


def _is_deprecated(acc: Account) -> bool:
    return bool(acc.name) and any(m in acc.name for m in Account._DEPRECATED_ACCOUNT_MARKERS)


def _label(acc) -> str:
    return f"#{acc.id} {acc.name}" if acc else '(-)'


def _classify(all_accounts):
    """يصنّف كل حساب مرتبط حسب القواعد الخمس. يُستدعى مرتين في كل تشغيل:
    مرة على الحالة الحقيقية، ومرة على الحالة المحاكاة بعد تطبيق إصلاحات
    AUTO-FIX (في الذاكرة، قبل أي commit) للتحقق أنها تصل للنتيجة المتوقعة.

    يُرجع قائمة "قرارات" (decisions)، كل عنصر:
      {account, target, issue, action, confidence ('HIGH'|'MANUAL'), reason}
    بالإضافة إلى already_correct وchecked.
    """
    by_id = {a.id: a for a in all_accounts}
    linked = [a for a in all_accounts if a.memo_account_id is not None]

    decisions = []
    already_correct = 0
    seen_pairs = set()
    duplicate_unlink_ids = set()

    targets_count = {}
    for a in linked:
        targets_count.setdefault(a.memo_account_id, []).append(a)

    for target_id, pointers in targets_count.items():
        if len(pointers) <= 1:
            continue
        target = by_id.get(target_id)
        deprecated_pointers = [p for p in pointers if _is_deprecated(p)]
        non_deprecated_pointers = [p for p in pointers if not _is_deprecated(p)]

        if deprecated_pointers and len(non_deprecated_pointers) <= 1:
            for p in deprecated_pointers:
                duplicate_unlink_ids.add(p.id)
                decisions.append({
                    'account': p, 'target': target,
                    'issue': 'duplicate_target', 'action': f'فك الربط مع {target.id}',
                    'confidence': 'HIGH',
                    'reason': 'الحساب موسوم كمتروك، ولا يوجد أكثر من منازع نشط واحد على الهدف',
                })
        else:
            decisions.append({
                'account': None, 'target': target,
                'issue': 'duplicate_target', 'action': 'لا إجراء',
                'confidence': 'MANUAL',
                'reason': 'أكثر من منازع نشط (غير متروك) -- ' + ', '.join(_label(p) for p in pointers),
            })

    for a in linked:
        if a.id in duplicate_unlink_ids:
            continue
        target = by_id.get(a.memo_account_id)

        if target is None:
            decisions.append({
                'account': a, 'target': None,
                'issue': 'broken_reference', 'action': 'لا إجراء',
                'confidence': 'MANUAL', 'reason': 'الهدف غير موجود في القاعدة',
            })
            continue

        if target.id == a.id:
            decisions.append({
                'account': a, 'target': None,
                'issue': 'self_reference', 'action': 'فسخ الربط',
                'confidence': 'HIGH', 'reason': 'الحساب يشير لنفسه',
            })
            continue

        pair_key = frozenset({a.id, target.id})
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)

        if target.memo_account_id == a.id:
            if bool(target.tracks_weight) == bool(a.tracks_weight):
                decisions.append({
                    'account': a, 'target': target,
                    'issue': 'type_mismatch', 'action': 'لا إجراء',
                    'confidence': 'MANUAL',
                    'reason': f'كلا الحسابين tracks_weight={a.tracks_weight}، يحتاج قراراً بشرياً',
                })
            else:
                already_correct += 1
            continue

        if target.memo_account_id is not None:
            if target.id in duplicate_unlink_ids:
                continue
            decisions.append({
                'account': a, 'target': target,
                'issue': 'one_way_link', 'action': 'لا إجراء',
                'confidence': 'MANUAL',
                'reason': f'الطرف الآخر يشير لحساب ثالث (#{target.memo_account_id}) لا لهذا الحساب',
            })
            continue

        if _is_deprecated(a) or _is_deprecated(target):
            decisions.append({
                'account': target, 'target': a,
                'issue': 'one_way_link', 'action': 'لا إجراء',
                'confidence': 'MANUAL',
                'reason': 'أحد الطرفين موسوم متروك -- لا يمكن إكمال الربط تلقائياً',
            })
            continue

        if bool(target.tracks_weight) == bool(a.tracks_weight):
            decisions.append({
                'account': a, 'target': target,
                'issue': 'type_mismatch', 'action': 'لا إجراء',
                'confidence': 'MANUAL',
                'reason': f'كلا الحسابين tracks_weight={a.tracks_weight}، يحتاج قراراً بشرياً',
            })
            continue

        decisions.append({
            'account': target, 'target': a,
            'issue': 'one_way_link', 'action': f'إنشاء الربط العكسي مع {a.id}',
            'confidence': 'HIGH',
            'reason': 'الطرف الآخر يشير إليه بالفعل ولا يوجد تعارض',
        })

    return {'checked': len(linked), 'already_correct': already_correct, 'decisions': decisions}


def _apply_auto_fixes(decisions, created_by: str):
    """يطبّق كل قرار HIGH عبر account_pair_service (flush بلا commit).
    يُرجع (fixed_count, errors)."""
    fixed = 0
    errors = []
    for d in decisions:
        if d['confidence'] != 'HIGH':
            continue
        try:
            if d['issue'] == 'self_reference':
                unlink_account(d['account'], created_by=created_by)
            elif d['issue'] == 'duplicate_target':
                unlink_account(d['account'], created_by=created_by)
            elif d['issue'] == 'one_way_link':
                link_accounts(d['account'], d['target'], created_by=created_by)
            fixed += 1
        except AccountPairLinkError as exc:
            errors.append((d, f'رفضته الخدمة: {exc}'))
        except Exception as exc:
            errors.append((d, f'خطأ غير متوقَّع: {exc}'))
    db.session.flush()
    return fixed, errors


MAX_CONVERGE_ITERATIONS = 10


def _converge(created_by: str):
    """يطبّق AUTO-FIX، يُعيد التصنيف، ويكرر ذلك حتى لا يبقى أي قرار HIGH --
    لأن إصلاح حالة واحدة قد "يحرّر" حالة أخرى لم تكن قابلة للإصلاح وقت
    التصنيف الأول (مثال حقيقي من الإنتاج: فسخ حساب #1213 المتروك عن #1072
    يُصفّر memo_account_id لـ#1072 نفسه أيضاً -- لأنهما كانا مرتبطين
    ببعضهما تبادلياً -- فيتحول ربط #1074 بـ#1072 من "متعارض" إلى "قابل
    للإكمال تلقائياً" فوراً، دون أي تعارض جديد). لا commit هنا أبداً --
    فقط flush، يستخدمها كل من المعاينة (تُتبَع بـrollback دائماً) والتنفيذ
    الفعلي (تُتبَع بـcommit لو نجحت كل الفحوصات).

    يُرجع: (total_fixed, all_errors, final_classification, iterations).
    """
    total_fixed = 0
    all_errors = []
    iterations = 0
    final_classification = None

    while iterations < MAX_CONVERGE_ITERATIONS:
        iterations += 1
        final_classification = _classify(Account.query.all())
        auto_fix_now = [d for d in final_classification['decisions'] if d['confidence'] == 'HIGH']
        if not auto_fix_now:
            break
        fixed, errors = _apply_auto_fixes(auto_fix_now, created_by=created_by)
        total_fixed += fixed
        all_errors.extend(errors)
        if errors:
            break

    return total_fixed, all_errors, final_classification, iterations


def _print_table(decisions, title: str):
    if not decisions:
        return
    print(f"\n=== {title} ({len(decisions)}) ===")
    print(f"{'الحساب':<8}{'المشكلة':<20}{'الإجراء المقترح':<28}{'الثقة':<8}السبب")
    print('-' * 100)
    for d in decisions:
        acc_id = d['account'].id if d['account'] else (d['target'].id if d['target'] else '-')
        print(f"{acc_id:<8}{d['issue']:<20}{d['action']:<28}{d['confidence']:<8}{d['reason']}")


def run(apply: bool) -> int:
    with app.app_context():
        initial = _classify(Account.query.all())
        decisions = initial['decisions']
        auto_fix = [d for d in decisions if d['confidence'] == 'HIGH']
        manual_review = [d for d in decisions if d['confidence'] == 'MANUAL']

        # تحقق التداخل: مضمون بنيوياً (memo_account_id حقل واحد لكل حساب)
        # لكنه يُتحقَّق منه فعلياً، لا يُفترَض فقط.
        auto_fix_ids = {d['account'].id for d in auto_fix if d['account']}
        manual_ids = set()
        for d in manual_review:
            if d['account']:
                manual_ids.add(d['account'].id)
            if d['target']:
                manual_ids.add(d['target'].id)
        overlap = auto_fix_ids & manual_ids

        print(f"{'='*60}")
        print(f"{'تطبيق فعلي' if apply else 'DRY RUN -- لا كتابة'}")
        print(f"{'='*60}")
        print(f"Checked: {initial['checked']}")
        print(f"Already correct: {initial['already_correct']}")

        _print_table(auto_fix, 'AUTO-FIX (سيُصلَح تلقائياً)')
        _print_table(manual_review, 'MANUAL REVIEW')

        by_issue_auto = {}
        for d in auto_fix:
            by_issue_auto[d['issue']] = by_issue_auto.get(d['issue'], 0) + 1
        by_issue_manual = {}
        for d in manual_review:
            by_issue_manual[d['issue']] = by_issue_manual.get(d['issue'], 0) + 1

        print(f"\n{'HIGH CONFIDENCE (سيصلح تلقائياً عند --apply)':<50}")
        print('-' * 50)
        for issue, count in sorted(by_issue_auto.items()):
            print(f"{issue:<20}: {count}")
        if not by_issue_auto:
            print("(لا يوجد)")

        print(f"\n{'MANUAL REVIEW':<50}")
        print('-' * 50)
        for issue, count in sorted(by_issue_manual.items()):
            print(f"{issue:<20}: {count}")
        if not by_issue_manual:
            print("(لا يوجد)")

        broken_count = by_issue_manual.get('broken_reference', 0) + by_issue_auto.get('broken_reference', 0)
        self_count = by_issue_manual.get('self_reference', 0) + by_issue_auto.get('self_reference', 0)
        # self_reference يُصلَح دائماً تلقائياً (لا حالة MANUAL له) -- الفحص هنا
        # يتحقق فقط أنه لم يظهر بصورة غير متوقَّعة في MANUAL.
        self_manual_count = by_issue_manual.get('self_reference', 0)

        print(f"\n{'SAFETY CHECKS':<50}")
        print('-' * 50)
        print(f"{'Broken references':<26}: {'PASS' if broken_count == by_issue_manual.get('broken_reference', 0) else 'INFO'} ({broken_count} يحتاج مراجعة يدوية دائماً)")
        print(f"{'Self references (manual)':<26}: {'PASS' if self_manual_count == 0 else 'FAIL'} ({self_manual_count})")
        print(f"{'Overlap auto/manual':<26}: {'PASS' if not overlap else 'FAIL'} ({len(overlap)})")

        if overlap:
            print(f"\n🛑 تحقق التداخل فشل: {sorted(overlap)} ظهر في الفئتين معاً -- توقف، هذا خطأ برمجي.")
            return 1

        # ── Verify: تطبيق AUTO-FIX في الذاكرة (flush بلا commit)، مع تكرار
        # الدورة حتى التقارب (إصلاح حالة قد يُحرّر حالة أخرى لم تكن قابلة
        # للإصلاح عند التصنيف الأول -- مثال حقيقي: فسخ #1213 المتروك عن
        # #1072 يُصفّر #1072 نفسه، فيتحول ربطها بـ#1074 من متعارض لقابل
        # للإكمال فوراً). نتحقق من النتيجة النهائية قبل أي commit فعلي.
        created_by_preview = 'repair_all_memo_account_links_preview'
        fixed, errors, final, iterations = _converge(created_by=created_by_preview)

        final_auto_fix = [d for d in final['decisions'] if d['confidence'] == 'HIGH']
        final_manual = [d for d in final['decisions'] if d['confidence'] == 'MANUAL']
        final_manual_by_issue = {}
        for d in final_manual:
            final_manual_by_issue[d['issue']] = final_manual_by_issue.get(d['issue'], 0) + 1

        conflicting_ops = len(errors)
        # التقارب يجب أن يصل لصفر auto-fix متبقٍّ، بلا أخطاء، وألا يظهر أي
        # نوع مخالفة جديد لم يكن موجوداً أصلاً (الإصلاح يُفترض أن يُقلّص
        # المشاكل لا أن يُنشئ نوعاً جديداً منها) ولا عدد أكبر لنوع موجود.
        new_issue_types = set(final_manual_by_issue) - set(by_issue_manual)
        increased_counts = {
            issue: (final_manual_by_issue[issue], by_issue_manual.get(issue, 0))
            for issue in final_manual_by_issue
            if final_manual_by_issue[issue] > by_issue_manual.get(issue, 0)
        }
        idempotent_ok = (
            not final_auto_fix
            and not conflicting_ops
            and not new_issue_types
            and not increased_counts
            and iterations < MAX_CONVERGE_ITERATIONS
        )

        print(f"{'Conflicting operations':<26}: {'PASS' if conflicting_ops == 0 else 'FAIL'} ({conflicting_ops})")
        print(f"{'Convergence iterations':<26}: {iterations} {'(⚠️ بلغ الحد الأقصى)' if iterations >= MAX_CONVERGE_ITERATIONS else ''}")
        print(f"{'Idempotency preview':<26}: {'PASS' if idempotent_ok else 'FAIL'}")
        if not idempotent_ok:
            print(f"   AUTO-FIX المتبقي بعد التقارب: {len(final_auto_fix)} (يجب أن يكون 0)")
            print(f"   MANUAL REVIEW قبل: {by_issue_manual}")
            print(f"   MANUAL REVIEW بعد التقارب: {final_manual_by_issue}")
            if new_issue_types:
                print(f"   🛑 أنواع مخالفة جديدة ظهرت ولم تكن موجودة أصلاً: {new_issue_types}")
            if increased_counts:
                print(f"   🛑 ازداد عدد حالات موجودة (يجب أن يتناقص أو يبقى ثابتاً فقط): {increased_counts}")

        db.session.rollback()  # المعاينة أعلاه تُفسَخ دائماً -- لا commit إلا أدناه فقط لو نجحت كل الفحوصات.

        print(f"\n{'='*60}")
        if not idempotent_ok:
            print("❌ لن يُنفَّذ أي شيء -- معاينة الإصلاح لم تصل للنتيجة المتوقعة. راجع التفاصيل أعلاه.")
            return 1

        if not apply:
            print(f"✅ معاينة الإصلاح نجحت ({fixed} سيُصلَح عبر {iterations} دورة/دورات). أضف --apply للتنفيذ الفعلي.")
            return 0

        # المعاينة نجحت وapply=True -- نُعيد التطبيق فعلياً هذه المرة مع commit.
        fixed, errors, final, iterations = _converge(created_by='repair_all_memo_account_links')
        if errors or iterations >= MAX_CONVERGE_ITERATIONS:
            db.session.rollback()
            print(f"❌ فشل التنفيذ الفعلي بعد نجاح المعاينة (غير متوقَّع): errors={errors}, iterations={iterations}")
            return 1
        db.session.commit()
        print(f"✅ تم التنفيذ الفعلي: {fixed} إصلاحاً عبر {iterations} دورة/دورات.")
        return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    sys.exit(run(apply=args.apply))
