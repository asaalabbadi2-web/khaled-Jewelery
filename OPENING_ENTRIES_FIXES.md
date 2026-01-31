# إصلاحات القيود الافتتاحية (Opening Entries Fixes)

## المشاكل التي تم حلها

### 1. ✅ القيد لم يؤثر على الخزائن (Entries didn't affect safebox balances)

**المشكلة:** القيود اليومية لا تحدث أرصدة الحسابات المخزنة في قاعدة البيانات.

**الحل:**
- إضافة دالة `_update_account_balances_from_journal_lines()` في `backend/routes.py`
- ربط الدالة مع `add_journal_entry()` و `update_journal_entry()`
- إنشاء script `backend/recalculate_balances.py` لمزامنة البيانات الموجودة

**الملفات المعدلة:**
- `backend/routes.py`: إضافة تحديث تلقائي للأرصدة
- `backend/recalculate_balances.py`: script لإعادة حساب كل الأرصدة

**كيفية الاستخدام:**
```bash
cd backend
./venv/bin/python recalculate_balances.py
```

---

### 2. ✅ القيد لم يظهر كرصيد افتتاحي في كشف الحساب (Opening balance not shown separately)

**المشكلة:** القيود الافتتاحية تظهر كحركات عادية ولا يوجد رصيد افتتاحي منفصل.

**الحل:**
- تعديل `get_account_statement()` في `backend/routes.py`
- حساب الرصيد الافتتاحي من القيود ذات النوع `افتتاحي`
- استبعاد القيود الافتتاحية من قائمة الحركات
- إضافة حقول الرصيد الافتتاحي للذهب بالتفصيل

**الملفات المعدلة:**
- `backend/routes.py`: تصفية القيود الافتتاحية وحساب الرصيد الافتتاحي
- `frontend/lib/models/account_statement_model.dart`: إضافة `openingBalanceGoldDetails`

**البيانات المضافة في API:**
```json
{
  "opening_balance_cash": 10000.0,
  "opening_balance_gold_normalized": 50.0,
  "opening_balance_gold_details": {
    "18k": 0.0,
    "21k": 50.0,
    "22k": 0.0,
    "24k": 0.0
  }
}
```

---

### 3. ✅ عدم دمج حركة الحسابين في كشف الحساب (Financial and memo accounts not merged)

**المشكلة:** عند تسجيل نقد في الحساب المالي ووزن في حساب المذكرة، يظهران كحركتين منفصلتين.

**الحل:**
- إنشاء endpoint جديد `/api/accounts/<id>/statement_merged`
- دمج سطور القيود من الحساب المالي وحساب المذكرة المرتبط
- تجميع السطور حسب `journal_entry_id` لعرض حركة واحدة

**الملفات المعدلة:**
- `backend/routes.py`: إضافة `get_account_statement_merged()`
- `frontend/lib/api_service.dart`: إضافة `getAccountStatementMerged()`
- `frontend/lib/screens/account_statement_screen.dart`: إضافة زر "دمج الحسابين"

**المميزات:**
- اكتشاف تلقائي للحساب المرتبط (financial → memo أو memo → financial)
- تجميع ذكي للحركات من نفس القيد
- عرض معلومات عن الحسابين المدموجين في الاستجابة

**استخدام الميزة:**
1. افتح كشف حساب لأي حساب
2. فعّل خيار "دمج الحسابين" من شريط الأدوات
3. سيتم دمج الحركات من الحساب المالي وحساب المذكرة

---

## ملاحظات تقنية

### نظام تحديث الأرصدة التلقائي

عند إضافة أو تعديل قيد يومي:
1. يتم تحديد كل الحسابات المتأثرة (القديمة والجديدة)
2. لكل حساب، يتم إعادة حساب الرصيد من:
   - جميع سطور القيود اليومية (`JournalEntryLine`)
   - جميع سطور سندات القبض/الصرف (`VoucherAccountLine`)
3. يتم تحديث `balance_cash` و `balance_18k/21k/22k/24k` في جدول `Account`

### استبعاد القيود الافتتاحية

القيود من نوع `افتتاحي`:
- تُحسب في الرصيد الافتتاحي فقط
- لا تظهر في قائمة الحركات
- تُستخدم كنقطة بداية للأرصدة الجارية

### دمج الحسابات

الحسابات المالية والمذكرة المرتبطة:
- `Account.memo_account_id` يربط الحساب المالي بحساب المذكرة
- الحساب المالي يحتوي على نقد
- حساب المذكرة (`tracks_weight=True`) يحتوي على أوزان
- عند الدمج، يتم تجميع السطور حسب `journal_entry_id`

---

## الاختبار

### 1. اختبار تحديث الأرصدة:
```bash
cd backend
./venv/bin/python recalculate_balances.py
```

**النتيجة المتوقعة:**
```
🔄 جاري إعادة حساب أرصدة 48 حساب...
✅ 15 - صندوق النقدية نقد: 10000.00 → 0.00
✅ تم تحديث 1 حساب بنجاح
```

### 2. اختبار الرصيد الافتتاحي:
1. أنشئ قيد افتتاحي (`entry_type='افتتاحي'`)
2. افتح كشف الحساب
3. تحقق من ظهور الرصيد الافتتاحي بشكل منفصل

### 3. اختبار الدمج:
1. أنشئ قيد يحتوي على:
   - سطر في حساب مالي (نقد)
   - سطر في حساب مذكرة مرتبط (وزن)
2. افتح كشف الحساب المالي
3. فعّل "دمج الحسابين"
4. تحقق من ظهور سطر واحد يحتوي على النقد والوزن

---

## الملفات المتأثرة

### Backend:
- `backend/routes.py`: تعديلات على `get_account_statement()` وإضافة endpoints جديدة
- `backend/recalculate_balances.py`: script جديد لإعادة حساب الأرصدة

### Frontend:
- `frontend/lib/models/account_statement_model.dart`: إضافة `openingBalanceGoldDetails`
- `frontend/lib/api_service.dart`: إضافة `getAccountStatementMerged()`
- `frontend/lib/screens/account_statement_screen.dart`: إضافة زر "دمج الحسابين"

---

## التحسينات المستقبلية

1. **عرض القيود الافتتاحية بشكل منفصل:** إضافة قسم "القيود الافتتاحية" في كشف الحساب
2. **دمج تلقائي:** عرض الحسابات المدموجة بشكل افتراضي إذا كان هناك حساب مذكرة مرتبط
3. **تقرير الأرصدة:** إضافة تقرير يعرض جميع الحسابات مع أرصدتها الافتتاحية والجارية

---

## التاريخ
- **التاريخ:** 2025-01-23
- **المطور:** GitHub Copilot (Claude Sonnet 4.5)
- **الحالة:** مكتمل ✅
