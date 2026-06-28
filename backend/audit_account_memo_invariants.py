"""
audit_account_memo_invariants.py
===================================
تدقيق فقط -- لا يكتب أي شيء ولا يصحّح شيئاً. هذا ليس سكريبت إصلاح.

السياق: اكتُشف عبر حادثة حساب #1213 (انظر diagnose_latest_office_reservation.py
وfix_office6_weight_account_1213_to_1074.py) أن memo_account_id لا يخضع لأي
ضمان (invariant) دائم على مستوى النظام -- فقط Account.create_parallel_account()
يضبط الربط المتبادل عند الإنشاء عبر هذا المسار تحديداً، بينما 36 موضع كتابة
آخر في الكود (routes.py وخدمات الحسابات المختلفة) يكتبون memo_account_id
مباشرة دون أي تحقق. هذا فسّر أيضاً حادثة تاريخية سابقة مماثلة (حسابا
1074/1197 المتشابكان خطأً، انظر repair_memo_accounts.py).

هذا السكريبت يفحص كل حساب في النظام له memo_account_id، ويتحقق من 5 قواعد:

  1. broken_reference  -- الحساب الهدف غير موجود في القاعدة أصلاً.
  2. self_reference     -- الحساب يشير إلى نفسه.
  3. one_way_link       -- A.memo_account_id = B، لكن B.memo_account_id != A
                           (يجب أن تكون العلاقة متبادلة دائماً).
  4. duplicate_target   -- أكثر من حساب (مختلفين) يشيران لنفس الهدف.
  5. type_mismatch       -- الحسابان بنفس قيمة tracks_weight (يُفترض أن أحدهما
                           مالي False والآخر وزني True دائماً، لا نفس النوع).

يطبع تقريراً نهائياً: ✓ لكل قاعدة سليمة، ✗ مع التفاصيل لكل مخالفة. خروج
بحالة (exit code) غير صفرية لو وُجدت أي مخالفة -- يصلح لاستخدامه ضمن CI
أو فحص دوري مستقبلاً.

تشغيل (قراءة فقط):
    docker cp backend/audit_account_memo_invariants.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/audit_account_memo_invariants.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import Account


def _label(acc) -> str:
    if acc is None:
        return '(غير موجود)'
    return f"#{acc.id} {acc.name} (رقم {acc.account_number}, tracks_weight={acc.tracks_weight})"


def run() -> int:
    with app.app_context():
        all_accounts = Account.query.all()
        by_id = {a.id: a for a in all_accounts}
        linked = [a for a in all_accounts if a.memo_account_id is not None]

        broken_reference = []
        self_reference = []
        one_way_link = []
        type_mismatch = []

        for a in linked:
            target = by_id.get(a.memo_account_id)

            if target is None:
                broken_reference.append(a)
                continue

            if target.id == a.id:
                self_reference.append(a)
                continue

            if target.memo_account_id != a.id:
                one_way_link.append((a, target))

            if bool(target.tracks_weight) == bool(a.tracks_weight):
                type_mismatch.append((a, target))

        # duplicate_target: group by memo_account_id value, flag targets pointed to by >1 distinct account
        targets_count: dict[int, list] = {}
        for a in linked:
            if a.memo_account_id is not None:
                targets_count.setdefault(a.memo_account_id, []).append(a)
        duplicate_target = {
            target_id: pointers for target_id, pointers in targets_count.items()
            if len(pointers) > 1
        }

        print(f"إجمالي الحسابات: {len(all_accounts)} | لديها memo_account_id: {len(linked)}\n")

        ok = True

        print("1) broken_reference (الهدف غير موجود):")
        if broken_reference:
            ok = False
            for a in broken_reference:
                print(f"   ✗ {_label(a)} -> memo_account_id={a.memo_account_id} (غير موجود)")
        else:
            print("   ✓ سليم -- كل الأهداف موجودة.")

        print("\n2) self_reference (يشير لنفسه):")
        if self_reference:
            ok = False
            for a in self_reference:
                print(f"   ✗ {_label(a)} يشير لنفسه")
        else:
            print("   ✓ سليم -- لا يوجد أي حساب يشير لنفسه.")

        print("\n3) one_way_link (العلاقة ليست متبادلة):")
        if one_way_link:
            ok = False
            for a, target in one_way_link:
                print(f"   ✗ {_label(a)} -> {_label(target)} | لكن رجوع {target.id}.memo_account_id={target.memo_account_id} != {a.id}")
        else:
            print("   ✓ سليم -- كل الروابط متبادلة.")

        print("\n4) duplicate_target (أكثر من حساب يشير لنفس الهدف):")
        if duplicate_target:
            ok = False
            for target_id, pointers in duplicate_target.items():
                target = by_id.get(target_id)
                print(f"   ✗ الهدف {_label(target)} يُشار إليه من {len(pointers)} حساباً:")
                for p in pointers:
                    print(f"       - {_label(p)}")
        else:
            print("   ✓ سليم -- كل هدف يُشار إليه من حساب واحد فقط.")

        print("\n5) type_mismatch (الحسابان من نفس نوع tracks_weight):")
        if type_mismatch:
            ok = False
            seen = set()
            for a, target in type_mismatch:
                key = frozenset({a.id, target.id})
                if key in seen:
                    continue
                seen.add(key)
                print(f"   ✗ {_label(a)} <-> {_label(target)} (كلاهما tracks_weight={a.tracks_weight})")
        else:
            print("   ✓ سليم -- كل زوج فيه حساب مالي وحساب وزني (لا تطابق).")

        print(f"\n{'='*60}")
        print("✅ كل القواعد سليمة -- لا حاجة لأي إصلاح." if ok else "❌ توجد مخالفات تحتاج مراجعة (انظر التفاصيل أعلاه).")
        return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(run())
