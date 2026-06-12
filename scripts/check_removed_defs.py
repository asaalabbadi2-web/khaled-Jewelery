#!/usr/bin/env python3
"""يفحص الملفات الـ Python المُرحّلة (staged) ويحذّر لو أي دالة/كلاس top-level
أو method داخل class اختفت بالمقارنة مع HEAD.

الهدف: إمساك overwrite صغير (حذف دالة واحدة) ضمن commit شرعي — وهو نمط
لا تمسكه فحوصات عدد الأسطر الإجمالي.
"""

from __future__ import annotations

import re
import subprocess
import sys

DEF_RE = re.compile(r"^(?:async\s+)?def\s+(\w+)\s*\(")
CLASS_RE = re.compile(r"^class\s+(\w+)\b")
METHOD_RE = re.compile(r"^    (?:async\s+)?def\s+(\w+)\s*\(")


def run(args: list[str]) -> str:
    return subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE).stdout


def extract_names(source: str) -> set[str]:
    names: set[str] = set()
    for line in source.splitlines():
        for pattern in (DEF_RE, CLASS_RE, METHOD_RE):
            m = pattern.match(line)
            if m:
                names.add(m.group(1))
                break
    return names


def staged_python_files() -> list[str]:
    out = run(["git", "diff", "--cached", "--name-only", "--diff-filter=M"])
    return [f for f in out.splitlines() if f.endswith(".py")]


def main() -> int:
    blocked = False
    for path in staged_python_files():
        try:
            old_source = run(["git", "show", f"HEAD:{path}"])
        except subprocess.CalledProcessError:
            continue  # new file, nothing to compare

        try:
            new_source = run(["git", "show", f":{path}"])
        except subprocess.CalledProcessError:
            continue  # deleted file, handled by other checks

        removed = extract_names(old_source) - extract_names(new_source)
        if removed:
            blocked = True
            print(f"⚠️  WARNING: {path} — دوال/كلاسات اختفت بالمقارنة مع HEAD:")
            for name in sorted(removed):
                print(f"     - {name}")

    if blocked:
        print()
        print("❌ Commit محجوب: قد يكون هذا overwrite غير مقصود لدالة كانت موجودة.")
        print("   راجع: git diff --cached HEAD")
        print("   لو الحذف مقصود، تجاوز بـ: git commit --no-verify")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
