# تصميم: دورة حياة الدفعة ووسيلة الدفع

**حالة هذه الوثيقة: تصميم قبل الترحيل، لا سجل لعمل منتهٍ.** خلافاً لـ
[ACCOUNT_PAIR_ARCHITECTURE.md](ACCOUNT_PAIR_ARCHITECTURE.md) (مكتوبة بعد إنجاز
الترحيل)، هذه الحدود تُثبَّت **قبل** نقل أي سطر كود، تطبيقاً للدرس المستفاد من
`memo_account_id`: تصميم واجهة الخدمة قبل رؤية كل الحالات الفعلية أدّى لإعادة
تصميم مكلفة. هنا حُصرت القواعد أولاً (بحثان مستقلان عبر Explore + تحقق يدوي
مباشر من أكثر الملفات احتمالاً لاحتواء منطق مكرر)، ثم صُمِّمت الحدود.

## الحدود المعمارية الأربعة

### 1) Payment Method Definition -- موجودة بالفعل، لا تغيير مطلوب

**المسؤولية:** تعريف وسيلة الدفع نفسها، بلا أي معرفة بما يحدث بعد استخدامها.

**الملف:** `payment_methods_routes.py` -- **مؤكَّد بالفحص المباشر**: صفر إشارة
لـ`SettlementLine`، و`commission_timing` هنا تحقق/تخزين فقط
(`_normalize_commission_timing`) لا حساب فعلي. الحدود سليمة بالفعل اليوم.

يشمل: CRUD، نسب/قيمة العمولة، `commission_timing`، جداول التسوية/الإيداع،
ربط الحسابات، حارس الحذف الناعم (منع حذف وسيلة مستخدمة).

لا يعرف شيئاً عن: `InvoicePayment`، `SettlementLine`.

### 2) Payment Lifecycle -- الهدف: `PaymentLifecycleService`

**المسؤولية:** ما يحدث بعد إنشاء دفعة بوسيلة دفع معيّنة.

**المصدر الحالي (كله في `routes.py`):**
- `correct_invoice_payment_method()` (9225-9913) -- التصحيح الكامل والجزئي (2-way).
  يستدعي الدالة التالية عند استقبال `splits` كقائمة (N-way)، بعد فحص الحارس.
- `_correct_invoice_payment_method_multi_split()` (8940-9224، **معرَّفة قبل
  مستدعيها** -- تصحيح متعدد الأقسام (N-way). لا تكرّر فحص الحارس؛ تعتمد على
  أن المستدعي فحصه قبل التفويض إليها.
- `add_invoice_payment()` (9914+) -- إضافة دفعة لفاتورة قائمة.

يشمل: هل يجوز تصحيح وسيلة الدفع الآن (يستدعي السؤال 3)، تنسيق الاستدعاء
لحساب العمولة (يستدعي 4)، تنسيق إنشاء سند إعادة التصنيف (يستدعي 5)، تسجيل
`AuditLog`.

لا يعرف: تفاصيل حساب العمولة، تفاصيل بناء القيد -- ينسّق فقط، لا ينفّذ.

### 3) Settlement

**المسؤولية:** دورة المقاصة نفسها؛ يستقبل الدفعة بحالتها الحالية فقط، لا
يعرف كيف تُصحَّح وسيلة الدفع.

**المصدر الحالي:** `clearing_settlement_scheduler.py` (كامل الملف) + أجزاء من
`routes.py` (auto-settle ~30900، نشر سند التسوية ~31113-31138، التسوية
المؤجلة ~31631).

يشمل: `SettlementLine`، الجدولة الآلية، إنشاء سندات التسوية، حساب العمولة
وقت التسوية عندما `commission_timing='settlement'`.

### 4) Accounting

**المسؤولية:** إنشاء القيود فقط، وفق معطيات جاهزة، دون معرفة *لماذا* أُنشئ
القيد.

يشمل أنواع `reference_type` الحالية المؤكَّدة: `payment_method_correction`
(routes.py:9154, 9449)، وما يقابلها لـ`clearing_settlement`/`adjustment`/
`transfer` في مسارات أخرى من النظام.

## شجرة الخدمات

```
PaymentLifecycleService          (منسِّق -- Context 2)
│
├── SettlementStateService       (Context 3 يكشف الحالة فقط)
│       └── get_state(payment) -> NOT_SETTLED | PARTIALLY_SETTLED | FULLY_SETTLED
│
├── CommissionService            (Context 2/1 -- يقرأ سياسة الوسيلة من Context 1)
│       └── compute(amount, payment_method) -> {rate, amount, vat, net}
│
├── AccountingService            (Context 4)
│       └── create_reclassification_entry(...)
│
└── AuditService
        └── log(action, details)
```

`PaymentLifecycleService` منسِّق فقط، لا مكاناً تتراكم فيه القواعد -- نفس
الدرس من تجربة `memo_account_id`: خدمة صغيرة وواضحة أفضل من خدمة تتضخم بمرور
الوقت.

## قرار مثبَّت: سلوك `PARTIALLY_SETTLED`

**السؤال:** الحارس الحالي (routes.py:9266-9281) ثنائي فقط --
`SUM(SettlementLine.amount_settled) > 0.005` يُجمِّد التصحيح بالكامل، بلا
أي تمييز بين تسوية جزئية وكاملة. هل تستحدث `PARTIALLY_SETTLED` سلوكاً جديداً؟

**القرار:** لا. `PARTIALLY_SETTLED` تُعامَل مطابقةً لـ`FULLY_SETTLED` سلوكياً
(تُجمِّد التصحيح بالكامل) -- **لا تغيير عن السلوك الحالي**. الحالة الثلاثية
مفيدة للعرض/التقارير فقط في هذه المرحلة. السماح بتصحيح الجزء غير المسوَّى
تلقائياً (مطابقةً لميزة "split" اليدوية الموجودة في `correction_amount`،
routes.py:9354-9376، التي يحدِّدها المستخدم يدوياً اليوم -- لا اشتقاقاً من
`SettlementLine`) قرار **ميزة جديدة منفصلة**، خارج نطاق هذا الترحيل.

## خريطة الترحيل (الحالي → الهدف)

| المنطق الحالي | المواضع (مؤكَّدة بالفحص المباشر) | الخدمة الهدف |
|---|---|---|
| `SUM(SettlementLine.amount_settled)` مكرر | routes.py:9268, 31114, 31638؛ clearing_settlement_scheduler.py:245, 281, 315, 356, 527, 665, 850 (10 موضعاً، لا 6 كما قُدِّر أولاً) | `SettlementStateService.get_state()` |
| `_compute_commission_fields()` + فحوصات `commission_timing` المكرَّرة | routes.py:8921 (التعريف) + استدعاءات عند 9048, 9061, 9347, 9360, 9372, 10247-10254, 12445-12474, 14990-15021 | `CommissionService.compute()` |
| سند إعادة التصنيف (voucher + JE) | routes.py:9082-9168 (multi-split)، 9392-9461 (كامل) | `AccountingService.create_reclassification_entry()` |
| `AuditLog(action='correct_payment_method')` | routes.py:9170-9196, 9464-9491 | `AuditService.log()` (يُستدعى من `PaymentLifecycleService`) |
| الحارس `already_settled` | routes.py:9266-9281 | `PaymentLifecycleService.can_change_payment_method()` يستدعي `SettlementStateService` |

## خارج نطاق هذا الترحيل (عمداً)

- `devtools/backfill_safebox_from_vouchers.py`، `devtools/demo_scrap_purchase_invoice.py`،
  `devtools/repair_safebox_transactions.py` -- سكريبتات صيانة/بيانات تجريبية
  معزولة تُشغَّل يدوياً، لا مساراً حياً. تُرحَّل لاحقاً إن قررنا ذلك، بنفس
  أسلوب الدُفعة الثالثة (3C) في عمل `memo_account_id`.
- تكرار "Safe Box Resolution" (سلاسل fallback مختلفة في routes.py وposting_routes.py
  لتحديد خزنة الدفعة) -- مصدر تكرار حقيقي لكنه **مجال منفصل** عن دورة حياة
  وسيلة الدفع (`SafeBoxResolver`؟)، يُعالَج بقرار مستقل لاحقاً.
- `posting_routes.py` -- مؤكَّد أنه يتعامل فقط مع آثار الترحيل على دفتر
  الخزنة (إلحاق/قراءة)، لا قواعد دورة حياة. لا حاجة لأي ترحيل هنا.

## ما لا تفعله هذه الوثيقة

لا تنقل أي سطر كود. فقط تثبّت الحدود والمسؤوليات قبل أي ترحيل تدريجي
لمسارات `routes.py`، تماماً كما طُلب: تصميم أولاً، ثم تنفيذ أقل خطورة لأن كل
نقل يكون لواجهة معمارية محددة مسبقاً.
