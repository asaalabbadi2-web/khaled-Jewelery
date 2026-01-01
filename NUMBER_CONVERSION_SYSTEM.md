# نظام تحويل الأرقام التلقائي ✨

تم تطبيق نظام شامل لتحويل الأرقام العربية (٠-٩) والهندية/الفارسية (۰-۹) إلى أرقام عالمية (0-9) تلقائياً في جميع حقول الإدخال.

---

## 📁 الملفات الرئيسية

### 1. `frontend/lib/utils/arabic_number_formatter.dart`
**المحولات الأساسية:**
- `ArabicNumberTextInputFormatter` - للحقول الرقمية مع خيارات متقدمة
- `UniversalNumberTextInputFormatter` - للحقول النصية العامة
- `convertToWesternNumbers()` - دالة ثابتة للتحويل البرمجي

### 2. `frontend/lib/utils/global_number_converter.dart`
**أدوات مساعدة:**
- `UniversalTextField` - Widget جاهز مع تحويل تلقائي
- `withNumberConversion()` - Helper function
- `AutoNumberConversion` - Mixin للـ Widgets المخصصة

### 3. `frontend/GLOBAL_NUMBER_CONVERSION_GUIDE.md`
دليل شامل للمطورين مع أمثلة عملية وأسئلة شائعة.

---

## 🚀 البداية السريعة

### الطريقة الأسهل (موصى بها للمشاريع الجديدة)

```dart
import 'package:frontend/utils/global_number_converter.dart';

UniversalTextField(
  controller: myController,
  keyboardType: TextInputType.numberWithOptions(decimal: true),
  decoration: InputDecoration(labelText: 'الوزن بالجرام'),
  validator: (value) => value?.isEmpty ?? true ? 'مطلوب' : null,
)
```

### إضافة التحويل لحقول موجودة

```dart
import 'package:frontend/utils/arabic_number_formatter.dart';

TextFormField(
  controller: weightController,
  keyboardType: TextInputType.numberWithOptions(decimal: true),
  inputFormatters: [
    ArabicNumberTextInputFormatter(
      allowDecimal: true,
      allowNegative: false,
    ),
  ],
  decoration: InputDecoration(labelText: 'الوزن'),
)
```

---

## 🎯 الأمثلة العملية

### مثال 1: شاشة فاتورة البيع
في `sales_invoice_screen_v2.dart` تم تطبيق التحويل على:
- حقل الوزن (Weight)
- حقل أجرة المصنعية (Wage)
- حقل الإجمالي (Total)

```dart
TextFormField(
  controller: weightController,
  keyboardType: const TextInputType.numberWithOptions(decimal: true),
  inputFormatters: [
    ArabicNumberTextInputFormatter(
      allowDecimal: true,
      allowNegative: false,
    ),
  ],
  decoration: const InputDecoration(
    labelText: 'الوزن بالجرام',
    prefixIcon: Icon(Icons.scale),
  ),
)
```

### مثال 2: حقل نصي عام

```dart
import 'package:frontend/utils/global_number_converter.dart';

UniversalTextField(
  controller: addressController,
  decoration: InputDecoration(
    labelText: 'العنوان',
    hintText: 'شارع ١٢٣، بناء ٤٥', // سيتم تحويلها تلقائياً
  ),
  maxLines: 3,
)
```

---

## 🔄 كيفية تطبيق النظام على باقي الشاشات

### الخطوة 1: استيراد المكتبة

```dart
import '../utils/arabic_number_formatter.dart';
// أو
import '../utils/global_number_converter.dart';
```

### الخطوة 2: تحديد الحقول المناسبة

**للحقول الرقمية البحتة:**
- الأوزان (Weights)
- الأسعار (Prices)
- الكميات (Quantities)
- النسب المئوية (Percentages)

**للحقول النصية مع أرقام:**
- العناوين (Addresses)
- أرقام الهواتف (Phone Numbers)
- أرقام التعريف (IDs)
- الأسماء مع أرقام (Names with numbers)

### الخطوة 3: تطبيق التحويل

**للحقول الرقمية:**
```dart
TextFormField(
  inputFormatters: [
    ArabicNumberTextInputFormatter(
      allowDecimal: true,  // حسب الحاجة
      allowNegative: false,
    ),
  ],
  // ... بقية الخصائص
)
```

**للحقول النصية:**
```dart
UniversalTextField(
  // ... جميع الخصائص العادية
)
```

---

## 📋 قائمة الشاشات المقترحة للتحديث

### أولوية عالية 🔴
- [ ] `items_screen_enhanced.dart` - حقول الوزن والسعر
- [ ] `journal_entry_form.dart` - حقول المبالغ
- [ ] `melting_renewal_screen.dart` - حقول الأوزان
- [ ] `weight_closing_settings_screen.dart` - جميع الحقول الرقمية

### أولوية متوسطة 🟡
- [ ] `add_customer_screen.dart` - رقم الهاتف والعنوان
- [ ] `add_supplier_screen.dart` - رقم الهاتف والعنوان
- [ ] `employees_screen.dart` - الرواتب وأرقام الهواتف
- [ ] `accounting_mapping_screen_enhanced.dart` - الحقول الرقمية

### أولوية منخفضة 🟢
- [ ] `users_management_screen.dart` - أرقام الهواتف
- [ ] `offices_screen.dart` - العناوين والهواتف
- [ ] الشاشات الأخرى حسب الحاجة

---

## 🧪 الاختبار

### اختبار يدوي سريع
1. افتح الشاشة المحدثة
2. ضع المؤشر في أي حقل محدث
3. اكتب أرقام عربية: ١٢٣٤٥
4. تحقق من التحويل التلقائي إلى: 12345
5. جرب النسخ واللصق لنص يحتوي أرقام عربية/هندية

### اختبار برمجي
```dart
test('Arabic numbers conversion', () {
  final result = ArabicNumberTextInputFormatter.convertToWesternNumbers('الوزن: ٢٣.٥ جرام');
  expect(result, 'الوزن: 23.5 جرام');
});

test('Persian numbers conversion', () {
  final result = ArabicNumberTextInputFormatter.convertToWesternNumbers('قیمت: ۱۲۳۴ تومان');
  expect(result, 'قیمت: 1234 تومان');
});
```

---

## ⚙️ الخيارات المتقدمة

### ArabicNumberTextInputFormatter

```dart
ArabicNumberTextInputFormatter(
  allowDecimal: true,    // السماح بالفاصلة العشرية (12.5) ✅
  allowNegative: false,  // السماح بالأعداد السالبة (-10) ❌
)
```

### أمثلة الاستخدام

```dart
// للأوزان: أعداد موجبة مع فاصلة عشرية
ArabicNumberTextInputFormatter(allowDecimal: true, allowNegative: false)

// للكميات الصحيحة: أعداد صحيحة موجبة فقط
ArabicNumberTextInputFormatter(allowDecimal: false, allowNegative: false)

// للأرصدة: أعداد موجبة وسالبة مع فاصلة
ArabicNumberTextInputFormatter(allowDecimal: true, allowNegative: true)
```

---

## 🐛 معالجة المشاكل الشائعة

### المشكلة: التحويل لا يعمل
**الحل:** تأكد من إضافة الـ import:
```dart
import '../utils/arabic_number_formatter.dart';
```

### المشكلة: تعارض مع formatters أخرى
**الحل:** استخدم `withNumberConversion()`:
```dart
inputFormatters: withNumberConversion([
  LengthLimitingTextInputFormatter(10),
  // ... formatters أخرى
]),
```

### المشكلة: التحويل يعمل لكن Validation يفشل
**الحل:** استخدم `convertToWesternNumbers()` قبل parse:
```dart
validator: (value) {
  final converted = ArabicNumberTextInputFormatter.convertToWesternNumbers(value ?? '');
  final number = double.tryParse(converted);
  // ... بقية الـ validation
}
```

---

## 📊 الأرقام المدعومة

| العربية | الفارسية | الإنجليزية |
|---------|----------|------------|
| ٠       | ۰        | 0          |
| ١       | ۱        | 1          |
| ٢       | ۲        | 2          |
| ٣       | ۳        | 3          |
| ٤       | ۴        | 4          |
| ٥       | ۵        | 5          |
| ٦       | ۶        | 6          |
| ٧       | ۷        | 7          |
| ٨       | ۸        | 8          |
| ٩       | ۹        | 9          |

---

## 📝 ملاحظات للمطورين

1. **الاتساق**: استخدم نفس النهج في جميع أنحاء التطبيق
2. **الأداء**: التحويل فوري ولا يؤثر على الأداء
3. **التوافق**: يعمل مع Copy/Paste والإدخال المباشر
4. **الصيانة**: سهل الصيانة والتحديث مستقبلاً

---

## 🔗 روابط مفيدة

- **الدليل الشامل**: `frontend/GLOBAL_NUMBER_CONVERSION_GUIDE.md`
- **مثال عملي**: `frontend/lib/screens/sales_invoice_screen_v2.dart` (سطر 978-1025)
- **الأدوات**: `frontend/lib/utils/arabic_number_formatter.dart`
- **Helpers**: `frontend/lib/utils/global_number_converter.dart`

---

## ✅ الخلاصة

تم بناء نظام شامل وسهل الاستخدام لتحويل الأرقام تلقائياً:

✨ **3 طرق للاستخدام** - اختر ما يناسبك  
🎯 **مثال عملي مطبق** - في sales_invoice_screen_v2  
📖 **دليل شامل** - مع أمثلة وأسئلة شائعة  
🔧 **خيارات متقدمة** - للتحكم الكامل  
🚀 **جاهز للتطبيق** - على باقي الشاشات

---

**تم التطوير بواسطة:** فريق Yasar Gold & Jewelry POS  
**التاريخ:** ١ ديسمبر ٢٠٢٥
