#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# install_hooks.sh — تثبيت git hooks لحماية main من الـ overwrite
# ─────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
HOOKS_SRC="$ROOT_DIR/.githooks"
HOOKS_DST="$ROOT_DIR/.git/hooks"

# إنشاء مجلد المصدر إن لم يكن موجوداً
mkdir -p "$HOOKS_SRC"

# نسخ الـ hooks المحلية إلى .githooks لمشاركتها مع الفريق
for HOOK in pre-commit commit-msg pre-push; do
    SRC="$HOOKS_DST/$HOOK"
    DST="$HOOKS_SRC/$HOOK"
    if [ -f "$SRC" ]; then
        cp "$SRC" "$DST"
        chmod +x "$DST"
        echo "✅ نسخ $HOOK → .githooks/"
    fi
done

# تفعيل .githooks كمسار رسمي
git config core.hooksPath ".githooks"
echo ""
echo "✅ تم تثبيت git hooks من $HOOKS_SRC"
echo "   pre-commit  : منع overwrite في الملفات الحساسة"
echo "   commit-msg  : منع رسائل مبهمة (chore: updates ...)"
echo "   pre-push    : منع دفع حذف ضخم > 1500 سطر لـ main"
echo ""
echo "⚠️  للتجاوز الاضطراري فقط: git commit/push --no-verify"
