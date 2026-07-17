# ADR-020: Gate-Not-Calendar — كل تأجيل يسمّي شرط إغلاقه

**Status:** Accepted  
**Date:** 2026-07-17  
**Sprint:** S7 closure / S8+

---

## Policy or Law?

**Classification:** Law

| | تعريف | مثال من المشروع |
|---|---|---|
| **Law** | لا يجوز أن يتغيّر — انتهاكه يُسقط ضماناً. يُكتب كـ invariant مُختبَر. | "لا تأجيل بلا بوابة مسمّاة" |

**أين يعيش هذا القرار؟**
- [x] **كود مُختبَر** — كل ADR مفتوح وكل بند في أي audit يحمل `OPEN GATE:` مقروء آلياً
- [x] **بيانات / إعداد** — قائمة البوابات المفتوحة ترقّى في كل MIGRATION-AUDIT.md وكل ADR حيّ

---

## Context

### المشكلة المتكررة

التأجيل المكتوب كـ "milestone" أو "v1.2" أو "مستقبلاً" لا يُغلَق — يتبخّر.  
السبب: لا يوجد شيء ملموس يتوقف على إغلاقه. لا بوابة merge تسقط. لا جلسة تنتظر. لا عمل يُحجَب.  
نتيجة: الكود ينمو، والتأجيل يصبح بنية تحتية بحكم الأمر الواقع.

### التطبيق الأول: ADR-013 Sunset Clause (backend)

ADR-013 كسر هذا النمط في الـ backend:

```
"This ADR expires when Sprint 8 delivers a shared InventoryService."
"Any extension of Option B beyond Sprint 8 requires a new ADR."
```

التأجيل مربوط بحدث قابل للقياس (InventoryService تُسلَّم)، لا بتاريخ في تقويم.  
النتيجة: ADR-016 أغلق الغروب ووثّق ذلك بدقة. لم يتبخّر.

### التطبيق الثاني: `checkout/PAYMENT_FAILED` (frontend)

بدايةً سُجّل كـ `⚠️ deferred to CheckoutPage stories (v1.2)` في MIGRATION-AUDIT.md.  
لا بوابة. لا شيء يتوقف عليه. مؤجّل بذاكرة بمدة صلاحية.

الواقع العملي: رفض البطاقة في السوق السعودي ليس حالة هامشية — هو حدث يومي.  
هذه الشاشة هي الفارق بين عميل يعيد المحاولة وعداده ما زال حيًّا، وعميل يعتقد أن حجزه ضاع فيغادر.

أُعيد تسجيله بعد تطبيق هذا القانون:

```
🚫 MERGE GATE — blocks checkout integration session
CheckoutPage.stories.tsx / PaymentFailed must pass STATE_STORY_REGISTRY
before the integration session PR can merge.
```

الآن التأجيل مربوط بحدث (merge PR جلسة الوصل) لا بـ milestone.

---

## Decision

### القانون

**كل تأجيل يجب أن يسمّي شرط إغلاقه وما يُحجَبه.**

صيغة البوابة المطلوبة (في أي ADR، audit، أو todo):

```
OPEN GATE: <اسم البوابة>
Blocks: <PR / session / deployment>
Closes when: <شرط قابل للقياس>
Owner: <من يصنع القرار>
```

**التأجيل المقبول:** يحمل `OPEN GATE:` مكتوباً ويُدرج في قائمة البوابات المفتوحة.  
**التأجيل غير المقبول:** "v1.x" · "مستقبلاً" · "لاحقاً" · أي وصف لا يسمّي ما يُحجَب.

### القاعدة الفرعية: البوابة تُغلق بواسطة الجلسة التي تحرسها

البوابة الأفضل هي التي تكون هدفها ذاتها شرطاً في الجلسة أو الـ PR التي تحرسها.  
بهذا لا تستطيع الجلسة أن تنجح بدون إغلاق البوابة — الحارس والمحروس واحد.

مثال:
- جلسة الوصل هدفها "failure states are the goal"
- `checkout/PAYMENT_FAILED` بوابتها هي نفس الجلسة
- لا يمكن تحقيق الهدف بدون إغلاق البوابة → لن تُنسى

---

## Proof

### الـ invariant

أي ADR بحالة `Accepted — Transitional` يجب أن يحمل `Sunset:` أو `OPEN GATE:`.  
أي سطر في أي MIGRATION-AUDIT بعلامة ⚠️ يجب أن يُرقَّى إلى `🚫 OPEN GATE:` مع اسم ما يُحجَب.

### الاختبار الحالي (يدوي — يُؤتمَت في ADR-017 Law 1 sweep)

```bash
# كل ADR بحالة Transitional يملك Sunset clause
grep -l "Transitional" docs/adr/*.md | while read f; do
  grep -q "Sunset\|OPEN GATE" "$f" || echo "MISSING GATE: $f"
done

# كل audit entry بـ ⚠️ يملك رابطاً لبوابة
grep -rn "⚠️" apps/web/MIGRATION-AUDIT.md && echo "WARNING: unresolved deferral found"
```

---

## السجل المرجعي للبوابات المفتوحة

| البوابة | تُحجَب | تُغلَق عند | المالك |
|---|---|---|---|
| `checkout/PAYMENT_FAILED` — `CheckoutPage.stories.tsx/PaymentFailed` | merge PR جلسة الوصل | STATE_STORY_REGISTRY يمر بـ `PaymentFailed` export | checkout integration session |

*هذا الجدول يُحدَّث بكل ADR جديد يُعلن بوابة، ويُشطَب بكل بوابة تُغلَق.*

---

## Consequences

### Positive

- التأجيل المعلَن صريح: كل من يقرأ الكود يعرف ما المعلّق وما يتوقف عليه
- البوابات لا تتبخر لأن شيئاً ملموساً يتوقف عليها
- الـ ADR الحيّ (مثل ADR-013) يُغلَق بدليل لا بنسيان
- "فجوات حقيقية: صفر" تصبح جملة قابلة للتحقق، لا ادعاء

### Watch Out For

- البوابات المفتوحة يجب أن تُراجَع في بداية كل sprint — قائمة البوابات في هذا الجدول هي نقطة البداية
- بوابة تحجب بوابة أخرى (تسلسل) يجب أن يُوثَّق صراحةً لتجنّب الدورات

---

## Related

- [ADR-013](ADR-013-inventory-strangler-fig.md) — أول تطبيق للمبدأ: Sunset Clause في الـ backend
- [ADR-016](ADR-016-erp-sync-sunset-closed.md) — إغلاق غروب ADR-013، دليل أن المبدأ نجح
- [apps/web/MIGRATION-AUDIT.md](../../apps/web/MIGRATION-AUDIT.md) — §5 open gate: `checkout/PAYMENT_FAILED`
