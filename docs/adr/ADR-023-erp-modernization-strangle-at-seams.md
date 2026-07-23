# ADR-023 — ERP Modernization: Strangle at the Seams

**Status:** Accepted  
**Date:** 2026-07-18  
**Sprint:** 9 — Security Architecture (codifying an already-made decision)

---

## Policy or Law?

**Classification:** Both

| | تعريف | هذا القرار |
|---|---|---|
| **Law** | لا يجوز أن يتغيّر — انتهاكه يُسقط ضماناً. يُكتب كـ invariant مُختبَر. | M1 Seam Rule — كل كود ERP يُلمس لأغراض التكامل يُرفع للمعيار في لحظة اللمس |
| **Policy** | يتغيّر بتغيّر العالم أو التشغيل — يُخزَّن كبيانات أو متغير نشر. | M2 ترتيب الخنق — Business قد تُعيد الترتيب بملاحظة في Ledger |

**أين يعيش هذا القرار؟**
- [x] **كود مُختبَر** — قاعدة Seam (M1) مُطبَّقة بـ Ledger + CI Ratchet + gate في PR review
- [x] **بيانات / إعداد** — ترتيب الخنق (M2) قابل للتعديل بملاحظة في Ledger دون ADR جديد

*M1 هو القانون — يُطبَّق بالآلات. M2 هو السياسة — يُطبَّق بالوضوح.*

---

## Context

ERP (`backend/`) هو النظام الحي الذي يُشغّل العمل يومياً. يحتوي على منطق أعمال لسنوات،
وقاعدة بيانات حقيقية، وعمليات POS نشطة. إعادة كتابته تعني:

- أشهر من المخاطر على النظام الذي يُشغّل العمل
- صفر إيرادات في يوم الانتهاء
- المقبرة الكلاسيكية للـ Big-Bang rewrites

في نفس الوقت، "ربطه ونسيانه" (Connect-and-Forget) يعني:
- تتعفّن الواجهات (Seams) — نافذة INV-4 تصبح دائمة لا انتقالية
- التعويضات وحلول العمل تتراكم بدلاً من أن تُحلّ

**الملاحظة المهمة على الخريطة:** CLAUDE.md تُشير إلى `apps/erp` لكن الـ ERP يعيش فعلياً في
`backend/`. هذا drift موثَّق — يجب تصحيح CLAUDE.md عند أول فرصة مناسبة، وليس اليوم.

---

## Decision

**الـ ERP لن يُعاد كتابته.** يتحسّن من خلال آليتين فقط:

### M1 — قاعدة الواجهة (The Seam Rule)

> Boy-Scout-at-the-Seam: اترك كل كود ERP تلمسه للتكامل أفضل مما وجدته.

أي كود ERP يُلمس **لأغراض التكامل** يُرفع فوراً لمعيار المنصة:

| ما يُلمس | ما يُرفع للمعيار |
|----------|----------------|
| Route | Contract test (Law 0) |
| Business logic في route | ينتقل إلى service |
| SQL في route | يخرج منها |
| Transaction تُلمس | تصبح explicit |

**ما لا يُلمس:** كود ERP الذي التكامل لا يحتاجه **لا يُلمس.** الـ ERP يتحسّن بقدر ما يلتقي
بالمنصة — لا أقل (seams تتعفّن) ولا أكثر (الـ rewrite المحظور).

كل لمسة تُسجَّل في **Seam Ledger** (`docs/architecture/erp-seam-ledger.md`).

### M2 — الخنق المتعمّد (Deliberate Strangling)

بعد الإطلاق، بحسب ترتيب القيمة:

**M2.1 — INVENTORY** (الأولوية القصوى)
- استخراج إلى `packages/domain`؛ الـ POS يستدعيه.
- هذا هو Option A العائد من الباب الذي تركه ADR-016 مفتوحاً.
- إكماله يُغلق INV-4 بالكامل ويُتقاعد نافذة fail-open في Gate B.
- مرجع: ADR-013 §Sunset Clause — Option A هو الهدف المؤجَّل.

**M2.2 — INVOICING**
- يحمل `commerce_order_id` مسبقاً؛ الاستخراج التالي بعد Inventory.

**M2.3 — ACCOUNTING**
- الأخير؛ معظمه يعيش فعلاً في `packages/domain` منذ Milestone 2.

**شرط كل استخراج:**
- Sprint مستقل + ADR مرجعي خاص به
- Tests-first migration
- فترة تهدئة المطابقة (Reconciliation-quiet period): أسبوع واحد نظيف
  بلا نتائج (zero findings) قبل الانتقال للتالي

---

## Rejected Alternatives

### Big-Bang Rewrite
**السبب:** أشهر من المخاطر على النظام الذي يُشغّل العمل، صفر إيرادات في يوم الانتهاء.
المقبرة الكلاسيكية للـ rewrites الكبيرة. الـ ERP يمتلك منطق أعمال نادراً ما يكون موثَّقاً —
النقل يعني إعادة اكتشاف الحالات الحافة تحت ضغط الإنتاج.

### Connect-and-Forget (ربط بلا صيانة)
**السبب:** الواجهات تتعفّن. نافذة INV-4 تصبح دائمة بدلاً من انتقالية. كل عقد تكامل
غير مختبر هو دين يتضاعف — وليس دين يُسدَّد.

---

## Enforcement — Law 0 Machines

### Gate 1 — Seam Ledger

**الملف:** `docs/architecture/erp-seam-ledger.md`

جدول يتتبّع: ملف/route ERP مُلمَس · تاريخ · ما رُفع للمعيار · اختبارات مُضافة.

**القانون:** كل PR لتكامل يلمس `backend/` يجب أن يُضيف صفاً في الـ Ledger.
PR يلمس `backend/` بلا صف = رفض في الـ Review (checklist item في MR template).

### Gate 2 — Ratchet Metric (CI)

النسبة: `(routes مع contract tests) / (مجموع routes مُلمَسة)` — لا تنخفض أبداً.

**الآلة:** `scripts/erp_seam_ratchet.py` — يُشغَّل في CI عند أي تغيير في `backend/**`
أو `docs/architecture/erp-seam-ledger.md`. يُطبع المقياس ويفشل إذا انخفض.

**خط الأساس:** مُخزَّن في `docs/architecture/.erp-seam-ratchet`
(صيغة: `tested=N\ntotal=M`). يُحدَّث يدوياً بعد كل PR يُضيف اختباراً — رفع الخط.

### Gate 3 — MR Template Checklist

`.gitlab/merge_request_templates/Default.md` يحتوي checklist item:
```
- [ ] **ERP Seam (ADR-023):** إذا لمس هذا الـ PR أي ملف في `backend/` لأغراض التكامل —
      هل يوجد صف جديد في docs/architecture/erp-seam-ledger.md؟
```

### قانون أم سياسة؟

| الحكم | التصنيف | الآلة |
|------|--------|-------|
| M1 كل لمسة تكامل تُسجَّل وتُختبَر | **قانون** | Ledger + Ratchet + MR gate |
| M2 ترتيب Inventory → Invoicing → Accounting | **سياسة** | ملاحظة في Ledger تكفي لإعادة الترتيب |

---

## Consequences

### Positive

**لا توقف في العمل:** الـ ERP يُعالج POS transactions يومياً. هذا القرار يضمن
التحسّن المستمر دون أي توقف.

**الديون تُسدَّد عند الاتصال:** كل نقطة تكامل تتحوّل إلى معيار في لحظة لمسها —
لا تراكم للديون المخفية.

**INV-4 له طريق واضح للإغلاق الكامل:** M2.1 (Inventory extraction) يُغلق
النافذة التي تركها ADR-016 مفتوحة تحت "managed + measured".

**المطابقة قابلة للقياس:** Ratchet metric + Ledger = لأول مرة يمكن الإجابة على
"ما نسبة واجهات ERP المُغطّاة باختبارات؟" بشكل آلي.

### Watch Out For

**ضغط "لمسة صغيرة لا تستحق":** أي لمسة للتكامل — مهما بدت صغيرة — تستلزم صفاً
في الـ Ledger. لا استثناءات. "لمسة صغيرة" بلا صف = ثغرة في الـ Ratchet.

**M2 ليس تسلسلاً صارماً:** الترتيب Inventory → Invoicing → Accounting هو
قيمة ليس إجباراً. قد تُعيد Business ترتيبه — لكن بملاحظة في الـ Ledger، وليس بـ ADR جديد.

**فترة التهدئة قابلة للضغط:** الأسبوع الهادئ قبل كل استخراج قد يبدو ترفاً تحت
ضغط الإطلاق. هو ليس ترفاً — هو الدليل الوحيد أن المطابقة نظيفة.

---

## Related

- ADR-012 — Inventory Strangler Fig (dual source-of-truth موثَّق)
- ADR-013 — Sunset Clause (M2.1 هو Option A العائد من هذا الباب)
- ADR-016 — ERP Sync: الحالة الانتقالية التي يُنهيها M2.1
- `docs/architecture/erp-seam-ledger.md` — السجل الحي لكل لمسة تكامل
- `scripts/erp_seam_ratchet.py` — آلة قياس الـ Ratchet
- `.gitlab/merge_request_templates/Default.md` — gate المراجعة
