# Utils - الأدوات المساعدة

هذا المجلد يحتوي على الأدوات والوظائف المساعدة المستخدمة في جميع أنحاء التطبيق.

---

## 📁 الملفات

### `arabic_number_formatter.dart` ✨
**نظام تحويل الأرقام التلقائي**

يقوم بتحويل الأرقام العربية (٠-٩) والهندية/الفارسية (۰-۹) إلى أرقام عالمية (0-9) تلقائياً.

**المكونات الرئيسية:**
- `ArabicNumberTextInputFormatter` - للحقول الرقمية مع خيارات متقدمة
- `UniversalNumberTextInputFormatter` - للحقول النصية العامة
- `convertToWesternNumbers()` - دالة ثابتة للتحويل البرمجي

**مثال الاستخدام:**
```dart
import 'package:frontend/utils/arabic_number_formatter.dart';

TextFormField(
  inputFormatters: [
    ArabicNumberTextInputFormatter(
      allowDecimal: true,
      allowNegative: false,
    ),
  ],
)
```

**الميزات:**
- ✅ تحويل فوري أثناء الكتابة
- ✅ يعمل مع Copy/Paste
- ✅ يدعم الأعداد العشرية والسالبة
- ✅ لا يؤثر على الأداء

---

### `global_number_converter.dart` 🔧
**أدوات إضافية لتحويل الأرقام**

يوفر طرقاً إضافية لتطبيق تحويل الأرقام بسهولة.

**المكونات الرئيسية:**
- `UniversalTextField` - Widget جاهز مع تحويل تلقائي
- `withNumberConversion()` - Helper function
- `AutoNumberConversion` - Mixin للـ Widgets المخصصة
- `InputDecorationExtension` - Extension للتلميحات

**مثال الاستخدام:**
```dart
import 'package:frontend/utils/global_number_converter.dart';

// الطريقة 1: استخدام UniversalTextField
UniversalTextField(
  controller: myController,
  decoration: InputDecoration(labelText: 'الحقل'),
)

// الطريقة 2: استخدام withNumberConversion()
TextFormField(
  inputFormatters: withNumberConversion([
    // formatters أخرى
  ]),
)
```

**الميزات:**
- ✅ سهل الاستخدام
- ✅ مرونة عالية
- ✅ يحافظ على الاتساق

---

## 📖 الوثائق الشاملة

للحصول على دليل شامل مع أمثلة ومعلومات تفصيلية:

1. **الدليل التفصيلي:** `frontend/GLOBAL_NUMBER_CONVERSION_GUIDE.md`
2. **README الرئيسي:** `NUMBER_CONVERSION_SYSTEM.md` (في جذر المشروع)
3. **التقرير الكامل:** `AUTOMATIC_NUMBER_CONVERSION_REPORT.md` (في جذر المشروع)

---

## 🧪 الاختبارات

ملف الاختبار: `frontend/test/arabic_number_formatter_test.dart`

**تشغيل الاختبارات:**
```bash
cd frontend
flutter test test/arabic_number_formatter_test.dart
```

**النتائج:** ✅ جميع الاختبارات نجحت (16/16)

---

## 🚀 البداية السريعة

### للحقول الرقمية
```dart
import 'package:frontend/utils/arabic_number_formatter.dart';

TextFormField(
  controller: weightController,
  keyboardType: TextInputType.numberWithOptions(decimal: true),
  inputFormatters: [
    ArabicNumberTextInputFormatter(allowDecimal: true),
  ],
)
```

### للحقول النصية العامة
```dart
import 'package:frontend/utils/global_number_converter.dart';

UniversalTextField(
  controller: nameController,
  decoration: InputDecoration(labelText: 'الاسم'),
)
```

---

## 🎯 الأرقام المدعومة

| العربية | الفارسية | الإنجليزية |
|---------|----------|------------|
| ٠-٩     | ۰-۹      | 0-9        |

---

## 📞 الدعم

للأسئلة أو المشاكل:
- راجع الوثائق المذكورة أعلاه
- تحقق من المثال العملي في `sales_invoice_screen_v2.dart`
- تواصل مع فريق التطوير

---

**آخر تحديث:** ١ ديسمبر ٢٠٢٥
