"""account_pair_invariants.py
==============================
منطق تصنيف واحد مشترك لعلاقة Account.memo_account_id حسب القواعد الخمس.

السياق: قبل هذا الملف، كان audit_account_memo_invariants.py (التدقيق
المعروض على الإنتاج) وrepair_all_memo_account_links.py (الإصلاح/التحقق)
كل منهما له نسخته الخاصة من منطق "ما الذي يُعتبر مخالفة" -- فلو طُوِّرت
قاعدة في أحدهما ونُسي تطبيقها في الآخر، يصبح ما تعتبره الاختبارات سليماً
مختلفاً عمّا تعتبره أداة التدقيق سليماً على الإنتاج، دون أن يُلاحَظ ذلك.
هذا الملف هو مصدر الحقيقة الوحيد لهذا التصنيف؛ كل من الأداتين (والاختبارات)
يستدعيانه، فلا يوجد نسختان يمكن أن تنجرفا عن بعضهما.

القواعد الخمس:
  1. broken_reference  -- الحساب الهدف غير موجود في القاعدة أصلاً.
  2. self_reference     -- الحساب يشير إلى نفسه.
  3. one_way_link       -- A.memo_account_id = B، لكن B.memo_account_id != A.
  4. duplicate_target   -- أكثر من حساب (مختلفين) يشيران لنفس الهدف.
  5. type_mismatch       -- الحسابان بنفس قيمة tracks_weight.
"""

from __future__ import annotations

from models import Account


def is_deprecated(acc: Account) -> bool:
    return bool(acc.name) and any(m in acc.name for m in Account._DEPRECATED_ACCOUNT_MARKERS)


def label(acc) -> str:
    if acc is None:
        return '(-)'
    return f"#{acc.id} {acc.name}"


def classify(all_accounts):
    """يصنّف كل حساب مرتبط حسب القواعد الخمس.

    يُرجع dict فيه:
      - checked: عدد الحسابات المرتبطة (لها memo_account_id).
      - already_correct: عدد الأزواج السليمة تماماً.
      - decisions: قائمة قرارات، كل عنصر:
          {account, target, issue, action, confidence ('HIGH'|'MANUAL'), reason}
        'HIGH' = قابل للإصلاح تلقائياً بثقة كاملة عبر account_pair_service
        (لا غموض فيه)؛ 'MANUAL' = يحتاج قراراً بشرياً، لا يُصلَح تلقائياً أبداً.
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
        deprecated_pointers = [p for p in pointers if is_deprecated(p)]
        non_deprecated_pointers = [p for p in pointers if not is_deprecated(p)]

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
                'reason': 'أكثر من منازع نشط (غير متروك) -- ' + ', '.join(label(p) for p in pointers),
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

        if is_deprecated(a) or is_deprecated(target):
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


def is_clean(all_accounts) -> bool:
    """True فقط لو لم توجد أي مخالفة إطلاقاً (لا HIGH قابل للإصلاح، ولا
    MANUAL يحتاج مراجعة) -- الفحص المختصر الأكثر استخداماً في الاختبارات."""
    return len(classify(all_accounts)['decisions']) == 0
