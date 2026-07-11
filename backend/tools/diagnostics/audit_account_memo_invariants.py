"""
audit_account_memo_invariants.py
===================================
تدقيق فقط -- لا يكتب أي شيء ولا يصحّح شيئاً. هذا ليس سكريبت إصلاح.

السياق: اكتُشف عبر حادثة حساب #1213 (انظر diagnose_latest_office_reservation.py
وfix_office6_weight_account_1213_to_1074.py) أن memo_account_id لا يخضع لأي
ضمان (invariant) دائم على مستوى النظام -- فقط Account.create_parallel_account()
يضبط الربط المتبادل عند الإنشاء عبر هذا المسار تحديداً، بينما 33 موضع كتابة
آخر في الكود كانوا يكتبون memo_account_id مباشرة دون أي تحقق (كلهم رُحِّلوا
الآن لاستخدام account_pair_service فقط -- انظر سجل commits هذا الملف).

منطق الفحص نفسه (القواعد الخمس) لا يُعرَّف هنا -- يُستورَد من
account_pair_invariants.classify()، وهو نفس المنطق المستخدم في
repair_all_memo_account_links.py للتصنيف والإصلاح. هذا مقصود: لو كان لكل
أداة نسختها الخاصة من "ما يُعتبر مخالفة"، يمكن أن تنجرف الأداتان عن بعضهما
بمرور الوقت دون أن يُلاحَظ -- فيصبح ما تعتبره الاختبارات سليماً مختلفاً عمّا
يراه هذا التدقيق على الإنتاج.

القواعد الخمس (انظر account_pair_invariants.py للتفصيل الكامل):
  1. broken_reference   2. self_reference   3. one_way_link
  4. duplicate_target    5. type_mismatch

يطبع تقريراً نهائياً: ✓ لكل قاعدة سليمة، ✗ مع التفاصيل لكل مخالفة. خروج
بحالة (exit code) غير صفرية لو وُجدت أي مخالفة -- يصلح لاستخدامه ضمن CI
أو فحص دوري مستقبلاً.

لقطة مرجعية (snapshot): يكتب دائماً ناتجاً مفصّلاً بصيغة JSON (مساراً
افتراضياً مختوماً بالوقت، أو --json-out لتحديد مسار يدوياً) -- يُستخدم
كنقطة مقارنة "قبل/بعد" أي إصلاح آلي أو يدوي على الإنتاج.

تشغيل (قراءة فقط):
    docker exec yasargold-backend python backend/audit_account_memo_invariants.py
    docker exec yasargold-backend python backend/audit_account_memo_invariants.py --json-out /app/backend/audit_before.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import Account
from account_pair_invariants import classify, label

ISSUE_TITLES = {
    'broken_reference': '1) broken_reference (الهدف غير موجود)',
    'self_reference': '2) self_reference (يشير لنفسه)',
    'one_way_link': '3) one_way_link (العلاقة ليست متبادلة)',
    'duplicate_target': '4) duplicate_target (أكثر من حساب يشير لنفس الهدف)',
    'type_mismatch': '5) type_mismatch (الحسابان من نفس نوع tracks_weight)',
}
ISSUE_OK_MESSAGE = {
    'broken_reference': 'سليم -- كل الأهداف موجودة.',
    'self_reference': 'سليم -- لا يوجد أي حساب يشير لنفسه.',
    'one_way_link': 'سليم -- كل الروابط متبادلة.',
    'duplicate_target': 'سليم -- كل هدف يُشار إليه من حساب واحد فقط.',
    'type_mismatch': 'سليم -- كل زوج فيه حساب مالي وحساب وزني (لا تطابق).',
}


def _git_commit() -> str:
    """أفضل محاولة لمعرفة نسخة الكود وقت هذه اللقطة -- يُرجع 'unknown' بصمت
    لو .git غير متاح (وهي الحال على الإنتاج عادةً: Dockerfile ينسخ مجلد
    backend/ فقط، بلا .git من جذر المشروع)، فلا يُفترض أن يُعتمَد عليه دائماً
    -- generated_at (الطابع الزمني) هو المرجع الموثوق على الإنتاج."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=os.path.dirname(__file__),
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return 'unknown'


def _acc_dict(acc) -> dict | None:
    if acc is None:
        return None
    return {
        'id': acc.id,
        'name': acc.name,
        'account_number': acc.account_number,
        'tracks_weight': bool(acc.tracks_weight),
        'memo_account_id': acc.memo_account_id,
    }


def run(json_out: str | None) -> int:
    with app.app_context():
        all_accounts = Account.query.all()
        result = classify(all_accounts)
        decisions = result['decisions']

        by_issue: dict[str, list] = {issue: [] for issue in ISSUE_TITLES}
        for d in decisions:
            by_issue.setdefault(d['issue'], []).append(d)

        linked_count = sum(1 for a in all_accounts if a.memo_account_id is not None)
        print(f"إجمالي الحسابات: {len(all_accounts)} | لديها memo_account_id: {linked_count}\n")

        ok = not decisions
        for issue, title in ISSUE_TITLES.items():
            print(title + ':' if issue == 'broken_reference' else f"\n{title}:")
            items = by_issue.get(issue, [])
            if not items:
                print(f"   ✓ {ISSUE_OK_MESSAGE[issue]}")
                continue
            for d in items:
                a, t = d['account'], d['target']
                if issue == 'duplicate_target' and a is None:
                    print(f"   ✗ الهدف {label(t)}: {d['reason']}")
                elif t is None:
                    print(f"   ✗ {label(a)}: {d['reason']}")
                else:
                    print(f"   ✗ {label(a)} <-> {label(t)}: {d['reason']}")

        print(f"\n{'='*60}")
        print("✅ كل القواعد سليمة -- لا حاجة لأي إصلاح." if ok else "❌ توجد مخالفات تحتاج مراجعة (انظر التفاصيل أعلاه).")

        snapshot = {
            'generated_at': datetime.now().isoformat(),
            'git_commit': _git_commit(),
            'total_accounts': len(all_accounts),
            'accounts_with_memo_link': linked_count,
            'summary': {issue: len(items) for issue, items in by_issue.items()},
            'ok': ok,
            'details': {
                issue: [
                    {
                        'account': _acc_dict(d['account']),
                        'target': _acc_dict(d['target']),
                        'confidence': d['confidence'],
                        'reason': d['reason'],
                    }
                    for d in items
                ]
                for issue, items in by_issue.items()
            },
        }

        out_path = json_out or os.path.join(
            os.path.dirname(__file__),
            f"audit_account_memo_invariants_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        )
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
        print(f"\nلقطة مرجعية كاملة محفوظة في: {out_path}")

        return 0 if ok else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--json-out', default=None, help='مسار ملف JSON للقطة المرجعية (افتراضياً: مختوم بالوقت بجانب السكريبت)')
    args = parser.parse_args()
    sys.exit(run(json_out=args.json_out))
