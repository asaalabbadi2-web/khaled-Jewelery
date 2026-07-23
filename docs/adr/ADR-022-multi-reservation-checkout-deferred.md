# ADR-022 — Multi-Reservation Checkout (deferred, rules fixed)

**Status:** Accepted  
**Date:** 2026-07-18  
**Sprint:** v1.2 Groundwork — Phase 2 pre-agreement

---

## Policy or Law?

**Classification:** Both

| | تعريف | مثال من المشروع |
|---|---|---|
| **Law** | لا يجوز أن يتغيّر — انتهاكه يُسقط ضماناً. يُكتب كـ invariant مُختبَر. | "لا قطعة تُباع مرتين" · "لا سعر بلا snapshot" |
| **Policy** | يتغيّر بتغيّر العالم أو التشغيل — يُخزَّن كبيانات أو متغير نشر. | void_window · حدود الـ rate · cap value |

**أين يعيش هذا القرار؟**
- [x] **كود مُختبَر** — R1–R4 قوانين مُختبَرة عند تنفيذها في Phase 2
- [x] **بيانات / إعداد** — قيمة الـ cap (3) تُخزَّن في config؛ لا تُشفَّر في المنطق
- [ ] كلاهما

*القوانين مُعرَّفة الآن. الاختبارات تُكتب في Phase 2 — كل إضافة لـ endpoint قبلها ستكون استثناء بأثر رجعي (Law 0 + ADR-017 §Law 1).*

---

## Context

منصة «مجوهرات خالد» تعمل بمبدأ «Reserve, don't Cart»: كل قطعة فريدة لا تتكرر، والحجز يُثبّت السعر والقطعة 10 دقائق. في v1.2 يشتري العميل قطعة واحدة لكل جلسة.

الطلب المتوقع مستقبلاً: شراء عدة قطع في عملية دفع واحدة (multi-reservation single-payment). هذه الميزة مؤجَّلة لـ Phase 2، لكن قواعدها تُحدَّد الآن لثلاثة أسباب:

1. **منع إعادة التفاوض** — كل فريق يُنفِّذ Phase 2 يجد القواعد محدودة مسبقاً، لا سؤالاً مفتوحاً.
2. **توجيه بنية v1.2** — G1 (browsing strip) يُبنى ليستقبل قائمة reservations، لأن تغييره لاحقاً يُعيد كتابة كود موجود.
3. **توثيق الرفض المبرَّر** — البدائل المرفوضة (TTL extension، partial confirm، classic cart) مُوثَّقة مع أسبابها.

---

## Decision

**v1.2 تُطلق checkout قطعة واحدة فقط.** Multi-reservation single-payment = Phase 2.

القواعد التالية مُثبَّتة الآن وتحكم تنفيذ Phase 2. لا تنفيذ الآن — توثيق مُسبق فقط.

### R1 — BASKET DEADLINE = MIN(expires\_at)

وقت التذكير والعداد المعروض = أقرب مهلة انتهاء بين جميع الحجوزات المفتوحة، تُعرض حرفياً:

```
«N قطع محجوزة — أقرب مهلة تنتهي خلال mm:ss»
```

**قانون أم سياسة؟** قانون — صياغة العداد من أي مصدر آخر تُضلِّل العميل.  
**اختبار Phase 2:** `test('basket deadline = MIN(expiresAt) of all active reservations')`

---

### R2 — NO TTL EXTENSION عند إضافة قطعة

إضافة حجز جديد لا تُمدِّد عمر الحجوزات القائمة. الـ TTL الخاص بكل حجز يبدأ من لحظة إنشائه ولا يتأثر بأفعال الحجوزات الأخرى.

**السبب:** تمديد الـ TTL يُحوِّل السلة إلى أداة احتجاز مخزون — العميل يضيف قطعة كل 9 دقائق ويُقيِّد المعرض إلى ما لا نهاية.

**قانون أم سياسة؟** قانون — يحمي INV-1 (لا احتجاز دائم للمخزون).  
**اختبار Phase 2:** `test('adding a second reservation does not extend the first TTL')`

---

### R3 — ALL-OR-NOTHING CONFIRMATION

عند الدفع على basket متعدد:
- PaymentIntent واحد بمجموع كل الأسعار المُثبَّتة.
- عند webhook النجاح: تأكيد جميع الحجوزات في **معاملة واحدة** (single transaction) مع أقفال مُكتسَبة بترتيب `id` الأبجدي (deadlock discipline — ADR-011).
- إذا انتهت صلاحية أي حجز أو خُسِر قبل التأكيد → استرداد تلقائي كامل لكل المبلغ.
- **التأكيد الجزئي + الاسترداد الجزئي مرفوض في Phase 2** (البديل موثَّق أدناه).

**قانون أم سياسة؟** قانون — يحمي INV-3 (لا طلب بلا تأكيد حجز) وINV-7 (لا استرداد جزئي صامت).  
**اختبارات Phase 2:**
```
test('expired reservation before webhook → full refund')
test('all-or-nothing: no partial confirmation on webhook')
test('lock acquisition order follows sorted reservation_id (deadlock prevention)')
```

---

### R4 — CONCURRENT CAP: max 3 حجوزات نشطة لكل جلسة

الحد الأقصى 3 حجوزات نشطة في آنٍ واحد — يُطبَّق في الخدمة (service-side), لا في الواجهة فقط.

**السبب:** حماية مكافئ لـ R2 — بدون cap يستطيع العميل حجز مخزون المعرض كله.

**قانون أم سياسة؟**
- الـ enforcement نفسه: قانون — لا حجز رابع إطلاقاً بلا تحرير ما قبله.
- قيمة الـ cap (3): سياسة — تُخزَّن في config؛ تغييرها بلا ADR مقبول بقرار Product.

**اختبارات Phase 2:**
```
test('4th reservation rejected with 409 while 3 are active')
test('cap enforcement is server-side (not client-bypass-able)')
```

**v1.2:** الـ cap الفعلي = 1. الواجهة تُظهر رسالة «لديك قطعة محجوزة بالفعل — أكمل دفعها أو ألغِ حجزها أولًا». الانتقال إلى 3 في Phase 2 يغيِّر config فقط.

---

### R5 — DOMAIN DELTA (موثَّق، غير مُنفَّذ)

التغيير الذي تستلزمه Phase 2 في طبقة الـ Domain والقاعدة:

| الحالي (v1.2) | المطلوب (Phase 2) |
|---|---|
| `orders.reservation_id UNIQUE` | `order_items.reservation_id UNIQUE` |
| INV-3: «لا طلب بلا حجز مؤكَّد» | INV-3 تُصاغ: «لا **بند** طلب بلا حجز مؤكَّد» |
| INV-7: لا تغيير | INV-7: لا تغيير |

هذا الـ delta يُنفَّذ في Phase 2 بـ migration مُوثَّقة. الـ migration تُوصَّف كـ "توسيع للنموذج" لا كـ "تغيير لحكمه" — INV-3 يظل صحيحاً طوال الطريق.

---

## Proof

### Laws (Phase 2 — xfail witnesses)

كل قانون من R1–R4 يتحول إلى اختبار مُسجَّل كـ `xfail` (Known Gap) في اليوم الذي تبدأ فيه Phase 2. الاختبار يكون أحمر أولاً (Law 0 — unwitnessed gate is not trusted)، ثم يُمرَّر بعد التنفيذ.

### Policy (R4 cap value)

يُخزَّن في `config.py` أو متغير بيئة `MAX_ACTIVE_RESERVATIONS_PER_SESSION`. مالكه: Engineering + Product مشتركاً. يتغير بلا ADR جديد.

---

## Alternatives Rejected

### TTL Extension (رُفض — R2)

البديل: كل ما يُضاف يُمدِّد مهلة الـ basket إلى 10 دقائق جديدة.  
**السبب:** يُحوِّل الحجز من ضمانة دفع إلى احتجاز مخزون. يتعارض مع مبدأ «Reserve, don't Cart» ومع روح INV-1.

### Partial Confirmation (رُفض — R3)

البديل: يُكمَّل ما يمكن إكماله، ويُستعاد ثمن ما انتهى.  
**السبب:** معادلة المخاطر غير متوازنة:
- **فائدة:** المزيد من الإيراد (قطعتان تُباعان بدل أن لا شيء يُباع).
- **تكلفة:** تعقيد محاسبي/مصالحة غير متناسب، تجربة مستخدم مُربِكة («دُفع جزء واسترُد جزء»)، حالة أخطاء صعبة التتبع.

*إعادة النظر متاحة بعد Phase 2 إذا وجدت بيانات تُثبت أن الإيراد يُبرِّر التعقيد.*

### Classic Cart (رُفض — بنيوياً)

البديل: سلة تقليدية بدون حجز، التحقق من التوفر عند checkout.  
**السبب:** يتعارض بشكل جذري مع «Reserve, don't Cart»:
- يُخاطر بخسارة القطعة بين إضافتها للسلة وإتمام الدفع.
- يُكسر INV-3 (يتطلب بناءً مختلفاً كلياً للطبقة).
- المنافسة على القطع الفريدة لا تنفع معها سلة مفتوحة.

---

## Consequences

### Positive

- Phase 2 هي تنفيذ، لا تفاوض — القواعد محسومة اليوم.
- G1 (browsing strip) بُني ليستقبل قائمة reservations من اليوم الأول — تغيير v1.2→Phase 2 هو تغيير بيانات لا بنية.
- الـ cap في v1.2 (=1) مُوثَّق كسياسة، لا كقانون — الرفع إلى 3 هو config change بلا ADR.

### Watch Out For

- R3 (all-or-nothing) يتطلب **معاملة ذات مرحلتين** (two-phase commit أو idempotent webhook): webhook يُشغِّل تأكيد جميع الحجوزات أو لا شيء. هذه هي أصعب نقطة في التنفيذ.
- R5 (domain delta) يتطلب migration تُعيد كتابة علاقة `orders → reservations`. المرحلة الانتقالية تحتاج إلى خطة backfill واضحة.
- deadlock prevention (R3): ترتيب اكتساب الأقفال بـ sorted `reservation_id` يجب أن يُطبَّق في كل مسار يُعدِّل reservations — ليس فقط في webhook handler.

---

## Sunset Note

هذا ADR يحكم تنفيذ Phase 2. أي انحراف عن R1–R5 يستلزم ADR جديداً يستعرض تحديداً لماذا القاعدة المحددة لا تنطبق على الحالة الجديدة. «لم نكن نعلم» ليست مبرراً — القواعد مُعلَّقة هنا منذ اليوم.

---

## Related

- ADR-011 — Orders are Business Records (lock order, INV-3, INV-7)
- ADR-017 — Security Architecture (Law 1: route scan, deny-by-default)
- ADR-020 — Gate not Calendar (Law 0: unwitnessed gate is not trusted)
- `docs/architecture/architecture-v1.md` §INV-1, §INV-3, §INV-7
- `apps/web/src/components/checkout/BrowsingReservationStrip.tsx` — G1 strip (Phase 2 ready)
