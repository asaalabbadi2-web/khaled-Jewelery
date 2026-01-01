# دليل تحويل الأرقام التلقائي

## نظرة عامة
تم تطبيق نظام تحويل تلقائي للأرقام في التطبيق يقوم بتحويل الأرقام العربية (٠-٩) والأرقام الهندية/الفارسية (۰-۹) إلى أرقام عالمية (0-9) تلقائياً في جميع حقول الإدخال.

## الملفات الرئيسية

### 1. `lib/utils/arabic_number_formatter.dart`
يحتوي على:
- **`ArabicNumberTextInputFormatter`**: محول للحقول الرقمية فقط (مع خيارات للأعداد العشرية والسالبة)
- **`UniversalNumberTextInputFormatter`**: محول عام لجميع حقول النصوص
- **`convertToWesternNumbers()`**: دالة ثابتة لتحويل النصوص

### 2. `lib/utils/global_number_converter.dart`
يحتوي على:
- **`UniversalTextField`**: Widget جاهز يطبق التحويل تلقائياً
- **`withNumberConversion()`**: Helper function لإضافة التحويل لأي TextField
- **`AutoNumberConversion`**: Mixin لإضافة التحويل للـ Widgets المخصصة

## طرق الاستخدام

### الطريقة 1: استخدام UniversalTextField (الأسهل والموصى بها)

```dart
import 'package:frontend/utils/global_number_converter.dart';

// استبدل TextField أو TextFormField بـ UniversalTextField
UniversalTextField(
  controller: myController,
  decoration: InputDecoration(
    labelText: 'الوزن بالجرام',
  ),
  keyboardType: TextInputType.numberWithOptions(decimal: true),
  validator: (value) {
    // التحقق من الصحة هنا
    return null;
  },
)
```

### الطريقة 2: إضافة formatter يدوياً

```dart
import 'package:frontend/utils/arabic_number_formatter.dart';

// للحقول الرقمية فقط
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

// أو لجميع أنواع النصوص
TextField(
  controller: nameController,
  inputFormatters: [
    UniversalNumberTextInputFormatter(),
  ],
  decoration: InputDecoration(labelText: 'الاسم'),
)
```

### الطريقة 3: استخدام withNumberConversion() helper

```dart
import 'package:frontend/utils/global_number_converter.dart';

TextFormField(
  controller: myController,
  inputFormatters: withNumberConversion([
    // أضف formatters أخرى هنا إذا لزم الأمر
    FilteringTextInputFormatter.digitsOnly,
  ]),
  decoration: InputDecoration(labelText: 'رقم الهاتف'),
)
```

### الطريقة 4: تحويل نص برمجياً

```dart
import 'package:frontend/utils/arabic_number_formatter.dart';

String arabicText = "الوزن: ٢٣.٥ جرام";
String converted = ArabicNumberTextInputFormatter.convertToWesternNumbers(arabicText);
// النتيجة: "الوزن: 23.5 جرام"
```

## أمثلة عملية

### مثال 1: حقل رقمي للوزن
```dart
UniversalTextField(
  controller: _weightController,
  keyboardType: TextInputType.numberWithOptions(decimal: true),
  decoration: InputDecoration(
    labelText: 'الوزن بالجرام',
    prefixIcon: Icon(Icons.scale),
  ),
  validator: (value) {
    if (value == null || value.isEmpty) {
      return 'يرجى إدخال الوزن';
    }
    final weight = double.tryParse(value);
    if (weight == null || weight <= 0) {
      return 'يرجى إدخال وزن صحيح';
    }
    return null;
  },
)
```

### مثال 2: حقل نصي عام مع أرقام
```dart
UniversalTextField(
  controller: _addressController,
  decoration: InputDecoration(
    labelText: 'العنوان',
    hintText: 'مثال: شارع ١٢٣، بناء رقم ٤٥',
  ),
  maxLines: 3,
)
```

### مثال 3: استبدال TextField موجودة
```dart
// قبل:
TextField(
  controller: myController,
  decoration: InputDecoration(labelText: 'الحقل'),
)

// بعد (ببساطة استبدل TextField بـ UniversalTextField):
UniversalTextField(
  controller: myController,
  decoration: InputDecoration(labelText: 'الحقل'),
)
```

## الأرقام المدعومة

### أرقام عربية (العربية الشرقية)
- ٠ ← 0
- ١ ← 1
- ٢ ← 2
- ٣ ← 3
- ٤ ← 4
- ٥ ← 5
- ٦ ← 6
- ٧ ← 7
- ٨ ← 8
- ٩ ← 9

### أرقام فارسية/هندية (الأردو، الفارسية)
- ۰ ← 0
- ۱ ← 1
- ۲ ← 2
- ۳ ← 3
- ۴ ← 4
- ۵ ← 5
- ۶ ← 6
- ۷ ← 7
- ۸ ← 8
- ۹ ← 9

## خيارات ArabicNumberTextInputFormatter

```dart
ArabicNumberTextInputFormatter(
  allowDecimal: true,    // السماح بالأعداد العشرية (مثل 12.5)
  allowNegative: false,  // السماح بالأعداد السالبة (مثل -10)
)
```

## الأسئلة الشائعة

### هل يؤثر هذا على الأداء؟
لا، التحويل يتم بشكل فوري أثناء الكتابة ولا يؤثر على أداء التطبيق.

### هل يعمل مع Copy/Paste؟
نعم، يتم تحويل النصوص المنسوخة تلقائياً عند اللصق.

### ماذا لو أردت تعطيل التحويل لحقل معين؟
استخدم `TextField` أو `TextFormField` العادية بدون إضافة أي formatter للأرقام.

### كيف أضيف formatters إضافية؟
استخدم `withNumberConversion()` وأضف formatters أخرى داخل القائمة:
```dart
inputFormatters: withNumberConversion([
  LengthLimitingTextInputFormatter(10),
  FilteringTextInputFormatter.digitsOnly,
]),
```

## التوصيات

1. **للحقول الرقمية البحتة**: استخدم `ArabicNumberTextInputFormatter` مع الخيارات المناسبة
2. **للحقول النصية العامة**: استخدم `UniversalTextField` أو `UniversalNumberTextInputFormatter`
3. **للمشاريع الجديدة**: استخدم `UniversalTextField` في كل مكان لضمان الاتساق
4. **للمشاريع الموجودة**: استبدل تدريجياً أو أضف `withNumberConversion()` للحقول المهمة

## الترحيل التدريجي

إذا كان لديك تطبيق موجود، يمكنك الترحيل تدريجياً:

1. **ابدأ بالحقول الحرجة**: مثل الوزن، السعر، الكميات
2. **ثم الحقول الشائعة**: العناوين، أرقام الهواتف
3. **أخيراً الحقول العامة**: أسماء، ملاحظات، إلخ

مثال على الترحيل:
```dart
// مرحلة 1: أضف فقط للحقول الرقمية الحرجة
TextFormField(
  inputFormatters: [ArabicNumberTextInputFormatter()],
  // ... بقية الخصائص
)

// مرحلة 2: استبدل بـ UniversalTextField عندما تكون جاهزاً
UniversalTextField(
  // ... نفس الخصائص
)
```

## الدعم الفني

إذا واجهت أي مشاكل أو كان لديك أسئلة:
- راجع الأمثلة في `sales_invoice_screen_v2.dart`
- تحقق من ملفات الـ utils في `lib/utils/`
- اتصل بفريق التطوير
