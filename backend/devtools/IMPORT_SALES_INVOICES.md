# Import Sales Invoices (Excel → POS)

This devtool imports **sales invoices** (`invoice_type: "بيع"`) from an Excel-exported file.

## In-App Import (Flutter UI)

If you prefer not to run a script, the app includes an **Admin-only** screen:

- Menu: **Settings & Tools** → **Import Sales (Excel)**
- Flow: run **Dry-run** first (preview summary), then **Apply** to execute
- Safety: **Dedupe is always enabled** (it will skip invoices that already exist)

Backend endpoint used by the UI:

- `POST /api/devtools/import/sales-invoices` (multipart form-data: `file` + `apply`)

Supported inputs:
- Excel `.xlsx` (recommended)
- Excel-exported `.tsv` / `.csv`

## Expected Columns (Arabic)
Exported headers should match these (spelling/spacing should be close):

- `التاريخ`
- `اسم الموظف`
- `رقم الموظف` (matched to `Employee.employee_code`)
- `الفرع`
- `الصنف`
- `العيار`
- `أجرة الجرام`
- `العدد`
- `الوزن` (total line weight)
- `التكلفة`
- `الصافي`
- `الإجمالي`
- `النقد`
- `الشبكة`
- `نوع الشبكة`

The **first column** in the file (whatever its header is) is used as the **invoice group key**.

## Important Rules
- Weight handling: Excel `الوزن` is treated as **total line weight**.
  - The importer sends `weight_per_item = الوزن / العدد` to avoid double-counting.
- Price/Tax handling:
  - Backend expects `selling_price` and `tax_amount` **per item** when `quantity > 1`.
  - Importer divides line totals by quantity accordingly.
- Invoice-level totals/payments:
  - If `الإجمالي`/`الصافي` are repeated on every row (invoice-level report), importer detects that and allocates totals across items (by weight) without multiplying totals.

## Run (Dry-run)
From repo root:

```bash
export DATABASE_URL="sqlite:////absolute/path/to/app.db"
python backend/devtools/import_sales_invoices.py --input SalesDB.xlsx
```

Tip: Prefer an **absolute** SQLite path in `DATABASE_URL` to avoid confusion with relative paths.

Optional:
- Limit invoice groups:

```bash
python backend/devtools/import_sales_invoices.py --input SalesDB.xlsx --limit 10
```

## Run (Apply)
Creates invoices + accounting entries (side effects):

```bash
python backend/devtools/import_sales_invoices.py --input SalesDB.xlsx --apply
```

## Deduplication (Recommended)
By default, the importer performs a best-effort dedupe check and **skips** creating a sales invoice if it already exists with the same:
- `invoice_type`
- `date`
- `employee_id` (when provided)
- `customer_id` (when provided)
- `total` (within a small tolerance)

Additionally (to prevent collisions when totals are identical), the importer also considers invoice weight and an items signature.

This helps prevent duplicates when resuming or rerunning ranges.

To disable dedupe (NOT recommended):

```bash
python backend/devtools/import_sales_invoices.py --input SalesDB.xlsx --apply --no-dedupe
```

### Payment mismatch handling
By default, if payments don’t exactly match the invoice total, the importer adjusts/creates a cash remainder.
It also clamps very small rounding overages (e.g. payments sum exceeds total by 0.01).
To disable that behavior:

```bash
python backend/devtools/import_sales_invoices.py --input SalesDB.xlsx --no-assume-cash-remainder
```

## Notes / Troubleshooting
- If invoice creation auth is enabled (`require_auth_for_invoice_create`), the importer will stop.
  - Temporarily disable it in Settings, run import, then re-enable.
- Payment methods must exist and be active (at least cash + one card type). The importer matches by `payment_type` or Arabic keywords.

## Excel Preparation (للإنتاج بدون مشاكل)

هذه النقاط هي أهم ما يجب ضبطه في ملف الإكسل قبل الاستيراد على نسخة الإنتاج، بناءً على المشاكل التي تظهر عادةً (وتلك التي ظهرت معنا أثناء الاستيراد):

### 1) مفتاح المجموعة (العمود الأول)
- العمود الأول هو **Group Key** ويُستخدم لتجميع السطور في فاتورة واحدة.
- يجب أن يكون:
  - غير فارغ لكل سطر تابع لفاتورة.
  - ثابت لنفس الفاتورة عبر كل سطورها.
  - فريد لكل فاتورة (لا تعيد استخدام نفس الرقم لفاتورتين مختلفتين).
- تجنّب الدمج (Merged cells) في العمود الأول.

### 2) التاريخ
- يجب أن يحتوي كل سطر على `التاريخ`.
- إذا كان لديك سطور بلا تاريخ (فارغة)، املأها في Excel قبل التصدير (Fill Down) لكي لا يعتمد الاستيراد على "آخر تاريخ معروف".
- صيغة مفضلة: `YYYY-MM-DD` أو `YYYY/MM/DD`.

### 3) الموظف
- `رقم الموظف` يجب أن يكون ثابتًا ويمكن مطابقته مع `Employee.employee_code`.
  - أمثلة مقبولة عادةً: `102` أو `E-000102`.
- إذا كان ملف الإكسل يحتوي أحيانًا على رقم وأحيانًا على كود مختلف لنفس الموظف، وحّد الشكل قبل الاستيراد.

### 4) الأرقام (تنسيق الأعمدة الرقمية)
- الأعمدة الرقمية (`الوزن`, `العدد`, `الإجمالي`, `الصافي`, `النقد`, `الشبكة`, `أجرة الجرام`) يجب أن تكون أرقامًا فعلية، وليس نصوصًا تحتوي على فواصل/مسافات غريبة.
- تجنّب وجود فواصل آلاف غير متسقة. (السكريبت يحاول إزالة الفواصل، لكن الأفضل تنظيفها من المصدر).

### 5) السطور الفارغة/سطر المجموع
- احذف أي سطور فاصل/عناوين داخلية/مجاميع (Total) داخل نفس الشيت.
- أي سطر لا يحتوي بيانات صنف/وزن/عدد يُفضّل حذفه قبل التصدير.

### 6) إجمالي/صافي على مستوى الفاتورة
- إذا كان تقرير الإكسل يكرر `الإجمالي`/`الصافي` على كل سطر داخل نفس الفاتورة، فالسكريبت يحاول اكتشاف ذلك ويمنع تضاعف الإجمالي.
- مع ذلك، الأفضل (إن أمكن) أن تكون القيم على مستوى السطر أو أن يكون تكرارها منتظمًا بالكامل داخل المجموعة.

### 7) الشبكة ونوع الشبكة
- `نوع الشبكة` يجب أن يكون موحّدًا قدر الإمكان (مثل: `مدى`, `فيزا`, `ماستر`, ...).
- تأكد أن `الشبكة` تمثل مبلغ الشبكة على مستوى الفاتورة (أو تكرار منتظم سيتم التعامل معه).

## Production Preflight Checklist (قبل التشغيل على الإنتاج)

### أ) حماية البيانات
- خذ نسخة احتياطية من قاعدة البيانات قبل أي تشغيل.
- تأكد أن `DATABASE_URL` يشير لقاعدة بيانات الإنتاج الصحيحة (مسار مطلق للـ SQLite إن كان SQLite).

### ب) المتطلبات داخل النظام
- وجود عميل افتراضي (Cash customer) مثل: `عميل نقدي`.
- وجود SafeBox نقدي افتراضي (Cash) و SafeBox بنك/شبكة (Bank) (أو على الأقل واحد مناسب) مع تعيين الافتراضي.
- طرق الدفع `PaymentMethod` فعّالة ومربوطة بـ `default_safe_box_id`:
  - النقد → صندوق نقد
  - مدى/بطاقة/تحويل → صندوق بنك/شبكة

### ج) الإعدادات والصلاحيات
- إذا كانت `require_auth_for_invoice_create` مفعلة، عطّلها مؤقتًا أثناء الاستيراد ثم أعد تفعيلها.
- قرر هل ستسمح للسكريبت بإنشاء موظفين مفقودين:
  - استخدم `--create-missing-employees` إذا كانت بعض أكواد الموظفين غير موجودة في الإنتاج.

## Recommended Run Order (اقتراح تشغيل آمن)

1) Dry-run أولًا:

```bash
export DATABASE_URL="sqlite:////absolute/path/to/app.db"
python backend/devtools/import_sales_invoices.py --input SalesDB.xlsx
```

2) تطبيق على دفعات (لتقليل المخاطر):

```bash
python backend/devtools/import_sales_invoices.py --input SalesDB.xlsx --min-group 1 --max-group 50 --apply --create-missing-employees
python backend/devtools/import_sales_invoices.py --input SalesDB.xlsx --min-group 51 --max-group 100 --apply --create-missing-employees
```

3) تحقق من الاكتمال (بعد كل دفعة أو بعد النهاية):

```bash
python backend/devtools/verify_sales_import_completeness.py --input SalesDB.xlsx
```

## Report Reconciliation Note (مهم للتقارير)
- تقرير "ملخص المبيعات" لديه خيار `include_unposted` (تضمين غير المرحلة).
- إذا كان الخيار مفعّلًا، سيشمل فواتير غير مرحلة وقد تظهر المجاميع أعلى من ملف الإكسل حتى لو تم الاستيراد بشكل صحيح.

