# علاقة الحساب المالي↔الوزني (`Account.memo_account_id`)

السياق الكامل لكل ما يلي: حادثة حساب #1213 (مكتب تسكير فورية واشخاص) —
ربط مالي/وزني ظلّ يشير لحساب متروك شهوراً دون أن يُلاحَظ، لأن `memo_account_id`
كان حقلاً تكتبه 33 موضعاً مختلفاً مباشرة بلا أي تحقق مشترك.

## القاعدة

**ممنوع تعديل `memo_account_id` مباشرة في أي كود جديد.**

```python
# ❌ ممنوع
account.memo_account_id = other.id

# ✅ الطريقة الوحيدة
from account_pair_service import link_accounts, unlink_account
link_accounts(financial, memo, created_by='...')
unlink_account(account, created_by='...')
```

`link_accounts` يفرض: ربطاً ثنائي الاتجاه دائماً، عدم تطابق `tracks_weight`
بين الطرفين، رفض الحسابات الموسومة كمتروكة، وفسخ أي مؤشر قديم/متضارب على
أي من الطرفين تلقائياً (1:1 محفوظة دائماً).

الاستثناء الوحيد: `Account.create_parallel_account()` في `models.py` —
موجود من قبل، يضبط الربط الثنائي بشكل صحيح أصلاً.

## أي قاعدة تحقق جديدة → `account_pair_invariants.classify()`

لا تُضِف فحصاً جديداً في مكان آخر. `account_pair_invariants.classify()` هو
المصدر الوحيد لـ"ما يُعتبر مخالفة" لهذه العلاقة، ويستخدمه:

- `audit_account_memo_invariants.py` (تدقيق الإنتاج، read-only)
- `repair_all_memo_account_links.py` (تصنيف + إصلاح آلي محقَّق)
- `test_account_pair_invariants.py` (الاختبارات التكاملية)

أي قاعدة تُضاف هناك تستفيد منها الثلاثة معاً تلقائياً، فلا تنجرف عن بعضها.

## الطبقات الأربع (دفاع متعدد، لا طبقة واحدة كافية بمفردها)

1. **الخدمة** (`account_pair_service.py`) — الواجهة الرسمية الوحيدة للكتابة.
2. **ORM** (`Account._validate_memo_account_id` في `models.py`) — يرفض
   الإشارة الذاتية والربط بحساب متروك حتى لو تجاوز كود ما الخدمة.
3. **قاعدة البيانات** (`schema_guard.ensure_account_memo_pair_constraints`) —
   `CHECK`/`UNIQUE` يمنعان الفساد حتى خارج التطبيق (SQL مباشر، استيراد).
4. **التدقيق** (`audit_account_memo_invariants.py`) — يكتشف أي انحراف
   تاريخي أو مستقبلي بالمعيار نفسه الذي يستخدمه الإصلاح والاختبارات.

## الحالة الحالية

لا ديون تقنية **معروفة** في إدارة هذه العلاقة ضمن الكود الحالي، بعد توحيد
نقطة الكتابة ومنطق التحقق، وإضافة الحمايات على مستوى ORM وقاعدة البيانات،
وإثبات ذلك باختبارات تكاملية (`test_account_pair_invariants.py`). هذا لا
يعني استحالة ظهور احتياج جديد مستقبلاً — فقط أن التصميم الحالي يستوعبه عبر
توسيع `account_pair_invariants.classify()`، لا عبر مسار كتابة مباشر جديد.
