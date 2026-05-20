#!/bin/bash
# _safe_commit.sh — مراجعة آمنة قبل كل commit
# الاستخدام: bash _safe_commit.sh "رسالة الـ commit"

set -e
MSG="${1:-chore: updates}"

echo ""
echo "════════════════════════════════════════════"
echo "  ⚠️  SAFE COMMIT — مراجعة قبل git add -A"
echo "════════════════════════════════════════════"
echo ""

# ملفات مُعدلة
echo "📋 الملفات المُعدلة (غير staged):"
git status --short
echo ""

# حجم التغييرات
echo "📊 حجم التغييرات vs HEAD:"
git diff --stat HEAD 2>/dev/null | tail -5
echo ""

# فحص الملفات التي نقصت بشكل مريب
echo "🔍 فحص الملفات التي قد يكون نقص منها كود:"
WARNINGS=0
while IFS= read -r f; do
  if [ -f "$f" ] && [[ "$f" == *.dart || "$f" == *.py ]]; then
    old=$(git show HEAD:"$f" 2>/dev/null | wc -l || echo 0)
    new=$(wc -l < "$f" 2>/dev/null || echo 0)
    lost=$((old - new))
    if [ "$lost" -gt 20 ]; then
      echo "  ⬇️  تحذير: فقدان $lost سطر في: $f"
      echo "       (كان: $old سطر  →  الآن: $new سطر)"
      WARNINGS=$((WARNINGS + 1))
    fi
  fi
done < <(git diff HEAD --name-only 2>/dev/null)

if [ "$WARNINGS" -eq 0 ]; then
  echo "  ✅ لا توجد ملفات نقصت بشكل ملحوظ"
fi

echo ""

# طلب تأكيد
if [ "$WARNINGS" -gt 0 ]; then
  echo "══════════════════════════════════════════════════"
  echo "  ⛔  يوجد $WARNINGS ملف فيه تحذير فقدان أسطر!"
  echo "  اكتب  YES  للمتابعة رغم التحذيرات"
  echo "  أو اضغط Enter / Ctrl+C للإلغاء:"
  echo "══════════════════════════════════════════════════"
  read -r CONFIRM
  if [ "$CONFIRM" != "YES" ]; then
    echo ""
    echo "❌ تم الإلغاء. راجع الملفات المشار إليها أولاً."
    exit 1
  fi
else
  echo "اضغط Enter للمتابعة أو Ctrl+C للإلغاء..."
  read -r _
fi

# Staging
echo ""
echo "⏳ جارٍ git add -A ..."
git add -A

# عرض ما سيُضم في الـ commit
echo ""
echo "📦 ما سيُدرج في الـ commit:"
git diff --cached --stat
echo ""
echo "رسالة الـ commit: \"$MSG\""
echo ""
echo "اضغط Enter لتأكيد الـ commit، أو Ctrl+C للإلغاء:"
read -r _

# Commit + Push
if git diff --cached --quiet; then
  echo "ℹ️  لا يوجد شيء جديد للـ commit."
else
  git commit -m "$MSG"
fi

echo ""
echo "⏳ جارٍ git push ..."
git push

echo ""
echo "✅ تم بنجاح!"
