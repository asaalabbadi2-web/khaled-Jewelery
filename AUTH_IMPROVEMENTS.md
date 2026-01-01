# تحسينات نظام المصادقة والأمان

## ✅ التغييرات المنفذة

### 1. البنية التحتية للأمان (Backend)

#### إعدادات JWT محسّنة (`config.py`)
- نقل إعدادات JWT إلى متغيرات البيئة:
  - `JWT_SECRET_KEY`: المفتاح السري (إلزامي في الإنتاج)
  - `JWT_ALGORITHM`: خوارزمية التشفير (افتراضي: HS256)
  - `JWT_ACCESS_TOKEN_EXP_MINUTES`: مدة صلاحية access token (افتراضي: 60 دقيقة)
  - `JWT_REFRESH_TOKEN_EXP_DAYS`: مدة صلاحية refresh token (افتراضي: 7 أيام)

#### نماذج قاعدة البيانات الجديدة (`models.py`)
1. **TokenBlacklist**: لحظر tokens المستخدمة بعد logout
   - تخزين `jti` (JWT ID) مع تاريخ الانتهاء والسبب
   
2. **RefreshToken**: إدارة جلسات المستخدم القابلة للإلغاء
   - تخزين hash للـ token (أمان إضافي)
   - تتبع IP وUser Agent لكل جلسة
   - دعم token rotation عند التحديث
   
3. **LoginAttempt**: تسجيل محاولات تسجيل الدخول
   - لتطبيق rate limiting
   - للمراقبة الأمنية
   
4. **PasswordResetToken**: إعادة تعيين كلمة المرور
   - للإدارة أو المساعدة الفنية
   - tokens ذات صلاحية محدودة (15 دقيقة)

5. **توسعة AppUser بدعم التحقق الثنائي (2FA)**
   - `totp_secret`: المفتاح السري لـ OTP
   - `two_factor_enabled`: تفعيل/إيقاف
   - `two_factor_verified_at`: تاريخ آخر تحقق

#### Auto-migration (`schema_guard.py`)
- إضافة دالة `ensure_app_user_security_columns()` لإضافة أعمدة 2FA تلقائياً
- يتم تشغيلها عند بدء التطبيق دون الحاجة لـ Alembic migration يدوي

### 2. المسارات (Endpoints) الجديدة

#### تسجيل الدخول المحسّن (`POST /api/auth/login`)
**التحسينات:**
- ✅ Rate limiting: حد أقصى 5 محاولات فاشلة خلال دقيقة واحدة
- ✅ إصدار refresh token مع access token
- ✅ دعم خيار "تذكرني" (refresh token لمدة 30 يوم)
- ✅ دعم التحقق الثنائي (2FA) إذا كان مفعلاً
- ✅ تسجيل جميع محاولات الدخول في `LoginAttempt`
- ✅ تسجيل في AuditLog

**Request:**
```json
{
  "username": "sales2",
  "password": "123456",
  "remember_me": false,
  "otp": "123456"  // مطلوب فقط إذا كان 2FA مفعل
}
```

**Response:**
```json
{
  "success": true,
  "message": "تم تسجيل الدخول بنجاح",
  "token": "eyJhbGc...",
  "refresh_token": "KKd-tx...",
  "user": {...},
  "user_type": "app_user"
}
```

#### تسجيل الخروج (`POST /api/auth/logout`)
**الوظائف:**
- ✅ حظر access token الحالي (blacklist)
- ✅ إلغاء refresh token (revoke)
- ✅ تسجيل في AuditLog

**Request:**
```json
{
  "refresh_token": "optional-refresh-token"
}
```

**Headers:**
```
Authorization: Bearer <access_token>
```

#### تحديث الجلسة (`POST /api/auth/refresh`)
**الوظائف:**
- ✅ Token rotation: إلغاء الـ refresh القديم وإصدار واحد جديد
- ✅ التحقق من صلاحية المستخدم
- ✅ إصدار access token جديد

**Request:**
```json
{
  "refresh_token": "KKd-tx..."
}
```

**Response:**
```json
{
  "success": true,
  "token": "new_access_token",
  "refresh_token": "new_refresh_token"
}
```

#### إدارة الجلسات
1. **قائمة الجلسات** (`GET /api/auth/sessions`)
   - عرض جميع refresh tokens النشطة للمستخدم
   - معلومات: IP، User Agent، تاريخ الإنشاء/الاستخدام
   
2. **إلغاء جلسة** (`POST /api/auth/sessions/<id>/revoke`)
   - إلغاء جلسة محددة يدوياً

#### إعادة تعيين كلمة المرور (للإدارة)
1. **إنشاء token** (`POST /api/auth/password-reset/admin-create`)
   - يتطلب صلاحيات admin
   - إنشاء token لإعادة تعيين كلمة مرور المستخدم
   
2. **تأكيد إعادة التعيين** (`POST /api/auth/password-reset/confirm`)
   ```json
   {
     "token": "reset_token",
     "new_password": "new_password_here"
   }
   ```
   - يلغي جميع refresh tokens الموجودة للمستخدم

#### التحقق الثنائي (2FA)
1. **إعداد 2FA** (`POST /api/auth/2fa/setup`)
   - توليد TOTP secret
   - إرجاع otpauth:// URI للـ QR code
   
2. **تفعيل 2FA** (`POST /api/auth/2fa/enable`)
   ```json
   {
     "otp": "123456"
   }
   ```
   - يتطلب رمز OTP صحيح للتأكيد
   
3. **إيقاف 2FA** (`POST /api/auth/2fa/disable`)
   - يتطلب رمز OTP صحيح للتأكيد

### 3. تحديثات Flutter

#### ApiService (`lib/api_service.dart`)
**إضافات جديدة:**
- `refreshAccessToken()`: تحديث access token
- `logoutServerSide()`: استدعاء logout على الخادم
- `getStoredRefreshToken()`: قراءة refresh token المخزن

#### AuthProvider (`lib/providers/auth_provider.dart`)
**التحسينات:**
- ✅ حفظ refresh_token من استجابة login
- ✅ استدعاء `logoutServerSide()` قبل مسح البيانات المحلية
- ✅ مسح refresh_token عند logout

### 4. الاختبار

تم إنشاء سكريبت اختبار شامل: `backend/test_auth_flow.py`

**النتائج:**
```
✅ Login → Access + Refresh tokens
✅ List Sessions → عرض الجلسات النشطة
✅ Refresh → Token rotation (إصدار tokens جديدة)
✅ Logout → Blacklist + Revoke
✅ Reuse Blacklisted Token → 401 Unauthorized
```

## 🔐 الميزات الأمنية

1. **Token Blacklist**: منع إعادة استخدام tokens بعد logout
2. **Refresh Token Rotation**: تدوير tokens عند كل تحديث
3. **Rate Limiting**: حماية من هجمات brute force (5 محاولات/دقيقة)
4. **Session Management**: تتبع وإلغاء الأجهزة المتصلة
5. **2FA Support**: طبقة أمان إضافية اختيارية
6. **Audit Logging**: تسجيل جميع عمليات المصادقة
7. **Password Reset**: نظام آمن لإعادة تعيين كلمات المرور

## 📋 استخدام 2FA (اختياري)

### للمستخدم (AppUser):
1. **إعداد 2FA:**
   ```bash
   curl -X POST http://localhost:8001/api/auth/2fa/setup \
     -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json"
   ```
   - احفظ الـ `otpauth_uri` واستخدمه مع تطبيق Authenticator (Google Authenticator, Authy, etc.)

2. **تفعيل 2FA:**
   ```bash
   curl -X POST http://localhost:8001/api/auth/2fa/enable \
     -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" \
     -d '{"otp": "123456"}'
   ```

3. **تسجيل الدخول مع 2FA:**
   ```bash
   curl -X POST http://localhost:8001/api/auth/login \
     -H "Content-Type: application/json" \
     -d '{
       "username": "sales2",
       "password": "123456",
       "otp": "123456"
     }'
   ```

## ⚙️ الإعدادات المطلوبة

### Backend (.env أو environment variables):
```bash
# إلزامي في الإنتاج
JWT_SECRET_KEY=your-secret-key-here-change-in-production

# اختياري (افتراضيات موجودة)
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXP_MINUTES=60
JWT_REFRESH_TOKEN_EXP_DAYS=7
```

### Dependencies:
تم إضافة `pyotp==2.9.0` إلى `requirements.txt`

## 🔄 التوافق مع النظام الحالي

- ✅ يدعم `BYPASS_AUTH_FOR_DEVELOPMENT` كما هو
- ✅ يدعم User و AppUser
- ✅ لا يكسر تسجيل الدخول الحالي
- ✅ auto-migration للأعمدة الجديدة

## 🧪 التشغيل والاختبار

```bash
# تشغيل Backend
cd backend
source venv/bin/activate
python app.py

# تشغيل اختبار Auth Flow
python test_auth_flow.py
```

## 📊 مراقبة الأمان

يمكن مراقبة:
- محاولات تسجيل الدخول الفاشلة: `LoginAttempt` table
- الجلسات النشطة: `RefreshToken` table
- Tokens المحظورة: `TokenBlacklist` table
- سجل الأحداث: `AuditLog` table

---

**ملاحظة:** تم الحفاظ على التوافق الكامل مع النظام الحالي. جميع التحسينات اختيارية ويمكن تفعيلها تدريجياً.
