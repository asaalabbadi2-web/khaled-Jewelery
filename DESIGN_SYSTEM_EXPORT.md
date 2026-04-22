# Design System Export — مجوهرات خالد (Yasar Gold POS)

---

## 1. معلومات عامة

| البند | القيمة |
|---|---|
| **اسم النظام** | مجوهرات خالد — نظام نقاط البيع الذهبي |
| **الإطار التقني** | Flutter (Frontend) + Flask REST API (Backend) |
| **UI Library** | Material Design 3 (`useMaterial3: true`) |
| **لغة الواجهة** | عربي أساسي، مع دعم للإنجليزية (toggle) |
| **اتجاه الكتابة** | RTL (`Directionality.rtl` افتراضي) |
| **إصدار Flutter** | SDK ^3.9.2 |
| **إصدار Python/Flask** | Python 3.x / Flask + SQLAlchemy |
| **قاعدة البيانات** | SQLite (تطوير) / PostgreSQL (إنتاج) |
| **المنفذ الخلفي** | 8001 (`http://localhost:8001`) |
| **العيار الرئيسي** | 21 قيراط (`MAIN_KARAT = 21`) |

---

## 2. نظام الألوان

### الألوان الذهبية (الأساسية)

```dart
// من: frontend/lib/theme/app_theme.dart — class AppColors
primaryGold  = Color(0xFFD4AF37)  // ذهبي فاخر — اللون الرئيسي
darkGold     = Color(0xFFB8860B)  // ذهبي داكن — AppBar، تحديدات
mediumGold   = Color(0xFFCD9D3C)  // ذهبي متوسط
lightGold    = Color(0xFFF4E4C1)  // ذهبي فاتح — خلفيات بطاقات محددة
deepGold     = Color(0xFF9A7D0A)  // ذهبي عميق
```

### ألوان الحالات

```dart
success = Color(0xFF2E7D32)  // أخضر زيتوني
warning = Color(0xFFE65100)  // برتقالي محمر
error   = Color(0xFFD32F2F)  // أحمر
info    = Color(0xFF1976D2)  // أزرق
```

### ألوان العيارات (Karat Colors)

```dart
karat18 = Color(0xFFFF6B6B)  // أحمر فاتح
karat21 = Color(0xFFD4AF37)  // ذهبي كلاسيكي
karat22 = Color(0xFF4ECDC4)  // تركواز
karat24 = Color(0xFF9B59B6)  // بنفسجي
```

### ألوان أنواع الفواتير

```dart
invoiceSaleNew       = Color(0xFF2E7D32)  // أخضر زيتوني — بيع جديد
invoiceSaleScrap     = Color(0xFF00897B)  // تركواز غامق — بيع كسر
invoicePurchaseScrap = Color(0xFFD84315)  // برتقالي محمر — شراء كسر
invoicePurchaseNew   = Color(0xFF5E35B1)  // بنفسجي غامق — شراء جديد
invoiceReturn        = Color(0xFFE53935)  // أحمر — مرتجع
```

### ألوان الوضع الفاتح (Light Mode)

```
scaffoldBackground : #FAFAFA
surface / Card     : #FFFFFF
AppBar             : #B8860B (darkGold)
onSurface text     : #212121
divider            : Colors.grey[300]  ≈ #E0E0E0
input fill         : Colors.grey[50]   ≈ #FAFAFA
input border       : Colors.grey[300]  ≈ #E0E0E0
```

### ألوان الوضع الداكن (Dark Mode)

```
scaffoldBackground : #1A1A1A
surface / Card     : #2D2D2D
AppBar             : #2D2D2D
AppBar foreground  : #D4AF37 (primaryGold)
input fill         : #2D2D2D
input border       : Colors.grey[700]  ≈ #616161
divider            : Colors.grey[800]  ≈ #424242
```

---

## 3. الخطوط والطباعة

### عائلة الخط

**Cairo** (خط عربي/لاتيني من Google Fonts، مضمّن محلياً)

```yaml
# من: frontend/pubspec.yaml
fonts:
  - family: Cairo
    fonts:
      - asset: assets/fonts/Cairo-Regular.ttf        # weight: 400
      - asset: assets/fonts/Cairo-Bold.ttf           # weight: 700
      - asset: assets/fonts/Cairo-SemiBold.ttf       # weight: 600
      - asset: assets/fonts/Cairo-Light.ttf          # weight: 300
      - asset: assets/fonts/Cairo-ExtraLight.ttf     # weight: 200
      - asset: assets/fonts/Cairo-Black.ttf          # weight: 900
```

### أحجام النصوص (Typography Scale)

| المتغير | الحجم | الوزن | الاستخدام |
|---|---|---|---|
| `displayLarge` | 32px | 700 Bold | عناوين كبيرة جداً |
| `displayMedium` | 28px | 700 Bold | عناوين رئيسية |
| `displaySmall` | 24px | 700 Bold | عناوين صفحات |
| `headlineMedium` | 20px | 700 Bold | رؤوس أقسام |
| `headlineSmall` | 18px | 600 SemiBold | رؤوس فرعية |
| `titleLarge` | 16px | 600 SemiBold | عناوين بطاقات |
| `titleMedium` | 14px | 500 Medium | نصوص ثانوية |
| `bodyLarge` | 14px | 400 Regular | نص رئيسي |
| `bodyMedium` | 13px | 400 Regular | نص ثانوي |
| `bodySmall` | 12px | 400 Regular | تسميات صغيرة |

---

## 4. نظام المسافات والحدود

### Border Radius

```dart
Card / Dialog     : BorderRadius.circular(16)
Button            : BorderRadius.circular(12)
Input Field       : BorderRadius.circular(12)
Chip / Badge      : BorderRadius.circular(8)  // افتراضي Material
```

### Padding القياسية

```dart
ElevatedButton : EdgeInsets.symmetric(horizontal: 24, vertical: 12)
Card padding   : EdgeInsets.all(16)  // Material default
AppBar         : centerTitle: false
```

### Elevation / Shadow

```dart
Card elevation        : 2 (Light) / 4 (Dark)
FAB elevation         : 4 (Light) / 6 (Dark)
AppBar elevation      : 4
Drawer elevation      : 16
BottomNavBar elevation: 8
```

### Border / Divider

```dart
Input focused border width : 2px (primaryGold)
Input default border       : 1px (grey[300] / grey[700])
Divider thickness          : 1px
```

---

## 5. بنية الملفات (هيكل المشروع)

```
yasargold/
├── backend/                   # Flask REST API
│   ├── app.py                 # نقطة دخول التطبيق
│   ├── models.py              # نماذج قاعدة البيانات
│   ├── routes.py              # مسارات API الرئيسية
│   ├── config.py              # إعدادات النظام
│   ├── auth_routes.py         # مصادقة JWT
│   ├── utils.py               # أدوات مساعدة
│   ├── gold_price.py          # جلب سعر الذهب
│   ├── services/              # خدمات الأعمال
│   ├── devtools/              # أدوات التطوير
│   └── alembic/               # مهاجرات قاعدة البيانات
│
└── frontend/                  # Flutter App
    ├── pubspec.yaml
    ├── lib/
    │   ├── main.dart           # نقطة دخول Flutter
    │   ├── api_service.dart    # HTTP client
    │   ├── config.dart
    │   ├── theme/
    │   │   └── app_theme.dart  # 🎨 نظام الثيم الكامل
    │   ├── models/             # Flutter models
    │   ├── providers/          # State management (Provider)
    │   │   ├── auth_provider.dart
    │   │   ├── settings_provider.dart
    │   │   ├── quick_actions_provider.dart
    │   │   └── sales_race_refresh_provider.dart
    │   ├── screens/            # شاشات التطبيق
    │   │   ├── home_screen_enhanced.dart      # الرئيسية
    │   │   ├── login_screen.dart
    │   │   ├── invoices_list_screen.dart
    │   │   ├── sales_invoice_screen_v2.dart
    │   │   ├── purchase_invoice_screen.dart
    │   │   ├── customers_screen.dart
    │   │   ├── suppliers_screen.dart
    │   │   ├── items_screen_enhanced.dart
    │   │   ├── journal_entry_form.dart
    │   │   ├── accounts_screen.dart
    │   │   ├── safe_boxes_screen.dart
    │   │   ├── settings_screen_enhanced.dart
    │   │   ├── employees_screen.dart
    │   │   ├── reports/
    │   │   │   ├── admin_dashboard_screen.dart  # لوحة التحكم
    │   │   │   ├── reports_main_screen.dart
    │   │   │   ├── income_statement_report_screen.dart
    │   │   │   ├── trial_balance_screen_v2.dart
    │   │   │   └── ... (22 شاشة تقارير)
    │   │   └── ... (80+ شاشة إجمالاً)
    │   ├── widgets/            # مكونات قابلة للإعادة
    │   │   ├── app_logo.dart
    │   │   ├── gold_price_bar.dart
    │   │   ├── gold_price_ticker_bar.dart
    │   │   ├── account_picker_sheet.dart
    │   │   ├── party_picker_dialog.dart
    │   │   └── ...
    │   ├── pdf/                # مولّدات PDF
    │   ├── features/           # ميزات مستقلة
    │   ├── constants/
    │   ├── services/
    │   └── utils/
    └── assets/
        ├── fonts/              # Cairo font files
        ├── KHGL.png            # شعار ذهبي (gold variant)
        └── KHWL.png            # شعار أبيض (white variant)
```

---

## 6. مكونات الـ Layout الأساسية

### الشاشة الرئيسية (HomeScreenEnhanced)

**الملف:** [frontend/lib/screens/home_screen_enhanced.dart](frontend/lib/screens/home_screen_enhanced.dart)

البنية:
```
Scaffold
├── AppBar
│   ├── AppLogo (KHGL/KHWL حسب الثيم)
│   ├── GoldPriceBar / GoldPriceTickerBar (شريط سعر الذهب)
│   └── actions: [pendingApprovals badge, theme toggle, locale toggle, profile]
├── Drawer (القائمة الجانبية)
│   └── قوائم مجمّعة: المبيعات، المشتريات، المحاسبة، الإدارة، التقارير
├── Body
│   ├── SalesRaceLeaderboard (بطولة المبيعات — اختياري)
│   ├── QuickActions Grid (أزرار سريعة قابلة للتخصيص)
│   ├── KPI Summary Cards (إجمالي العملاء، الفواتير، الأصناف)
│   └── InvoicesList (آخر الفواتير)
└── BottomNavigationBar
    ├── الرئيسية
    ├── الفواتير
    ├── العملاء
    ├── الأصناف
    └── الإعدادات
```

**الـ AppBar:**
```dart
AppBarTheme(
  backgroundColor: AppColors.darkGold,   // #B8860B (Light)
  backgroundColor: Color(0xFF2D2D2D),    // Dark mode
  foregroundColor: Colors.white,
  titleTextStyle: TextStyle(
    fontFamily: 'Cairo', fontSize: 20, fontWeight: FontWeight.bold
  ),
)
```

**الـ Drawer:** قائمة جانبية RTL بخلفية `Colors.white` (Light) / `#1A1A1A` (Dark)، تحتوي على تجمعات نظامية مع ListTile مع أيقونات Material.

### شريط سعر الذهب (GoldPriceBar)

**الملف:** [frontend/lib/widgets/gold_price_bar.dart](frontend/lib/widgets/gold_price_bar.dart)

شريط ثابت أسفل الـ AppBar يعرض:
- سعر الأوقية (USD)
- التغيير اليومي (مبلغ + نسبة مئوية + سهم)
- أسعار الجرام لعيارات 18، 21، 22، 24 بالريال السعودي
- مؤشر بصري أخضر/أحمر لاتجاه السعر

---

## 7. مكونات أساسية (Design Tokens)

### Button (زر)

```dart
// ElevatedButton الافتراضي
ElevatedButton.styleFrom(
  backgroundColor: AppColors.primaryGold,  // #D4AF37
  foregroundColor: Colors.white,
  elevation: 2,
  padding: EdgeInsets.symmetric(horizontal: 24, vertical: 12),
  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
  textStyle: TextStyle(fontSize: 14, fontWeight: FontWeight.bold, fontFamily: 'Cairo'),
)
```

### Card (بطاقة)

```dart
CardThemeData(
  color: Colors.white,              // Light / Color(0xFF2D2D2D) Dark
  elevation: 2,                     // Light / 4 Dark
  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
  shadowColor: Colors.black.withOpacity(0.08),
)
```

### Input (حقل إدخال)

```dart
InputDecorationTheme(
  filled: true,
  fillColor: Colors.grey[50],       // Light / Color(0xFF2D2D2D) Dark
  border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
  enabledBorder: OutlineInputBorder(
    borderSide: BorderSide(color: Colors.grey[300])
  ),
  focusedBorder: OutlineInputBorder(
    borderSide: BorderSide(color: AppColors.primaryGold, width: 2)
  ),
  labelStyle: TextStyle(color: Colors.grey[700], fontFamily: 'Cairo'),
  hintStyle: TextStyle(color: Colors.grey[400], fontFamily: 'Cairo'),
)
```

### FAB (زر العمل العائم)

```dart
FloatingActionButtonThemeData(
  backgroundColor: AppColors.primaryGold,
  foregroundColor: Colors.white,   // Light / Color(0xFF1A1A1A) Dark
  elevation: 4,
)
```

### BottomNavigationBar

```dart
BottomNavigationBarThemeData(
  backgroundColor: Colors.white,          // Light / Color(0xFF2D2D2D) Dark
  selectedItemColor: AppColors.darkGold,  // #B8860B
  unselectedItemColor: Colors.grey[400],
  type: BottomNavigationBarType.fixed,
  elevation: 8,
  selectedLabelStyle: TextStyle(fontFamily: 'Cairo', fontWeight: FontWeight.bold, fontSize: 12),
)
// عناصر: الرئيسية · الفواتير · العملاء · الأصناف · الإعدادات
```

### AppLogo Widget

```dart
// الملف: frontend/lib/widgets/app_logo.dart
// نوعان:
AppLogo.gold(width: x)   // assets/KHGL.png — على خلفية فاتحة
AppLogo.white(width: x)  // assets/KHWL.png — على AppBar الداكن
// يختار تلقائياً بناءً على لون النص المجاور
```

---

## 8. لوحة التحكم (Admin Dashboard)

**المسار:** [frontend/lib/screens/reports/admin_dashboard_screen.dart](frontend/lib/screens/reports/admin_dashboard_screen.dart)

### المكونات الرئيسية:
- **فلتر الوقت:** اليوم / الشهر / السنة (`_TimeRange enum`)
- **بطاقات KPI:** المبيعات النقدية، المبيعات الوزنية، المشتريات، ربح الجرام
- **الخزائن (Vaults):** بطاقات قابلة للتوسيع والترتيب بالسحب، مع الرصيد النقدي والذهبي
- **تنبيهات النظام:** قائمة تنبيهات طافية قابلة للإغلاق
- **مخطط الاتجاه:** fl_chart (مبيعات vs مشتريات)

### API Endpoints المستخدمة:
```
GET /api/dashboard?period=today|month|year
GET /api/gram-profit?period=today|month|year
GET /api/system-alerts
GET /api/safe-boxes
```

### Responsive Scaling:
```dart
double _uiScale(BuildContext context) {
  final width = MediaQuery.sizeOf(context).width;
  if (width >= 1200) return 1.20;
  if (width >= 900)  return 1.12;
  if (width >= 600)  return 1.04;
  return 1.0;
}
```

---

## 9. نماذج البيانات (Data Models)

### Account (الحساب المحاسبي)
```
جدول: account
- id, account_number (String unique), name, type (Asset/Liability/Equity/Revenue/Expense)
- transaction_type: 'cash' | 'gold' | 'both'
- balance_cash (Float ر.س)
- balance_18k, balance_21k, balance_22k, balance_24k (Float جم)
- tracks_weight (Boolean)
- memo_account_id → رابط الحساب الوزني الموازي
- النظام المزدوج: الحساب المالي (cash) ↔ الحساب الوزني (gold، يبدأ رقمه بـ 7)
```

### Customer (العميل)
```
جدول: customer
- id, customer_code (C-000001), name, phone, email
- address_line_1/2, city, state, postal_code, country
- id_number, id_version_number, birth_date
- balance_cash, balance_gold_18k/21k/22k/24k
- account_category_id → ربط بشجرة الحسابات (1100/1110/1120)
```

### Supplier (المورد)
```
جدول: supplier
- id, supplier_code (S-000001), name, phone, email
- tax_number, classification, default_wage_type ('cash'|'gold')
- balance_cash, balance_gold_18k/21k/22k/24k
- gold_balance_weight, gold_balance_cash_equivalent
- account_category_id → (2100xxx موردو الذهب)
- default_safe_box_id → خزينة التسويات
```

### Item (الصنف)
```
جدول: item
- id, item_code (I-000001), name, barcode
- category_id, karat (String: '18'|'21'|'22'|'24'), weight (Float جم)
- has_stones, stones_weight, stones_value
- count, wage (أجرة المصنعية ر.س), manufacturing_wage_per_gram
- price, stock
- weight_in_main_karat() → تحويل للعيار 21
- wage_in_gold() → تحويل الأجرة لذهب
```

### Invoice (الفاتورة)
```
جدول: invoice
- أنواع: 'بيع' | 'شراء' | 'شراء من عميل' | 'مرتجع بيع' | 'مرتجع شراء' | 'شراء (مورد)'
- customer_id / supplier_id / office_id
- invoice_number (تسلسلي)
- safe_box_id, branch_id
- الحالة: مسودة / موافق عليها / مرفوضة
```

### SafeBox (الخزينة)
```
جدول: safe_box
- id, name, safe_type: 'cash'|'gold'|'bank'
- account_id → ربط بشجرة الحسابات
- balance_cash, balance_gold (جم)
```

### JournalEntry (قيد محاسبي)
```
جدول: journal_entry
- entry_type: 'cash' | 'gold' | 'both'
- is_posted (Boolean)
- entry_number, reference, description
- السطور: debit_cash/credit_cash + debit_weight/credit_weight لكل عيار
```

---

## 10. الأيقونات والأصول

| البند | التفاصيل |
|---|---|
| **مكتبة الأيقونات** | Material Icons (مدمجة في Flutter) |
| **شعار اللون الذهبي** | `assets/KHGL.png` |
| **شعار اللون الأبيض** | `assets/KHWL.png` |
| **مجلد الخطوط** | `frontend/assets/fonts/` |
| **مولّد باركود** | حزمة `barcode_widget` + `mobile_scanner` |
| **الرسوم البيانية** | حزمة `fl_chart` |
| **الحركات** | `flutter_staggered_animations` |

---

## 11. API Endpoints الرئيسية

```
Base URL: http://localhost:8001  (dev) | إنتاج: متغير بيئة API_BASE_URL

المصادقة (JWT Bearer Token):
POST   /api/auth/login
POST   /api/auth/refresh
POST   /api/auth/logout

العملاء والموردون:
GET    /api/customers
POST   /api/customers
GET    /api/suppliers
POST   /api/suppliers

الفواتير:
GET    /api/invoices
POST   /api/invoices
GET    /api/invoices/:id

المحاسبة:
GET    /api/accounts
GET    /api/journal-entries
POST   /api/journal-entries
GET    /api/gold_price

لوحة التحكم والتقارير:
GET    /api/dashboard?period=today|month|year
GET    /api/gram-profit
GET    /api/safe-boxes
GET    /api/system-alerts

السندات:
GET    /api/vouchers
POST   /api/vouchers
```

---

## 12. نصائح لقطات الشاشة المقترحة

للحصول على صورة كاملة عن الواجهة، يُستحسن التقاط:

1. **الشاشة الرئيسية** — `home_screen_enhanced.dart` (مع شريط الذهب + أزرار سريعة)
2. **لوحة التحكم** — `admin_dashboard_screen.dart` (KPI + خزائن + مخطط)
3. **فاتورة البيع** — `sales_invoice_screen_v2.dart` (جدول الأصناف 7 أعمدة)
4. **قائمة الفواتير** — `invoices_list_screen.dart` (ألوان حالات الفواتير)
5. **القيود المحاسبية** — `journal_entry_form.dart` (النظام المزدوج)
6. **شاشة الإعدادات** — `settings_screen_enhanced.dart`
7. **الوضع الداكن** — أي شاشة رئيسية مع Dark Mode مفعّل
8. **شريط سعر الذهب** — `gold_price_bar.dart` (عيارات 18/21/22/24)

---

## ملاحظات معمارية مهمة

- **النظام المزدوج (Dual Ledger):** كل حساب مالي (cash) له حساب وزني موازي (gold) — رقمه = `7` + رقم المالي. يُضمن توازن دفتر الأستاذ بالريال وبالجرام في آنٍ واحد.
- **منطق الأوزان:** جميع حسابات الأعمال تعتمد الوزن بالجرام لا القيمة النقدية كمرجع أساسي.
- **الإعداد:** `MAIN_KARAT = 21` هو العيار القياسي للتحويلات.
- **RTL-safe:** جميع الواجهات تستخدم `Directionality(textDirection: TextDirection.rtl)` أو تعتمد على إعداد Locale عربي.
- **الثيم:** `ThemeProvider` (Provider) يدير التبديل بين Light/Dark مع حفظ التفضيل في `SharedPreferences`.
