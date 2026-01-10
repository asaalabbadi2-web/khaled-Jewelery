"""
Decorators للمصادقة والتفويض
================================

يحتوي على:
- @require_auth: التحقق من تسجيل الدخول
- @require_permission: التحقق من الصلاحيات
- get_current_user: الحصول على المستخدم الحالي
"""

from functools import wraps
from flask import request, jsonify, g
import jwt
from datetime import datetime, timedelta
import os
import uuid

from typing import Optional, Dict

from config import (
    JWT_SECRET_KEY,
    JWT_DEV_FALLBACK_SECRET,
    JWT_ALGORITHM,
    JWT_ACCESS_TOKEN_EXP_MINUTES,
    JWT_IDLE_TIMEOUT_MINUTES,
)

from models import User, AppUser, db

try:
    from models import Settings
except Exception:  # pragma: no cover
    Settings = None

from config import ENABLE_REDIS_CACHE
from redis_client import get_redis

try:
    # نموذج اختياري (سيتوفر بعد إضافة الموديل في models.py)
    from models import TokenBlacklist
except Exception:  # pragma: no cover
    TokenBlacklist = None

try:
    from models import RefreshToken, SessionActivity
except Exception:  # pragma: no cover
    RefreshToken = None
    SessionActivity = None


def _now() -> datetime:
    return datetime.utcnow()


def _idle_timeout_seconds() -> int:
    # Default minutes come from env (config), but can be overridden by DB settings.
    try:
        minutes = int(JWT_IDLE_TIMEOUT_MINUTES)
    except Exception:
        minutes = 0
    if minutes <= 0:
        return 0

    enabled = True
    db_minutes = None

    enabled_key = 'settings:idle_timeout_enabled'
    minutes_key = 'settings:idle_timeout_minutes'
    cache_hit = False

    if ENABLE_REDIS_CACHE:
        r = get_redis()
        if r is not None:
            try:
                cached_enabled = r.get(enabled_key)
                cached_minutes = r.get(minutes_key)

                if cached_enabled is not None:
                    s = cached_enabled.decode('utf-8') if hasattr(cached_enabled, 'decode') else str(cached_enabled)
                    s = s.strip().lower()
                    enabled = s in ('1', 'true', 'yes', 'y', 'on')
                    cache_hit = True

                if cached_minutes is not None:
                    s2 = cached_minutes.decode('utf-8') if hasattr(cached_minutes, 'decode') else str(cached_minutes)
                    try:
                        db_minutes = int(str(s2).strip())
                    except Exception:
                        db_minutes = None
                    cache_hit = True
            except Exception:
                cache_hit = False

    if not cache_hit and Settings is not None:
        try:
            row = Settings.query.first()
            if row is not None:
                enabled = bool(getattr(row, 'idle_timeout_enabled', True))
                try:
                    db_minutes = int(getattr(row, 'idle_timeout_minutes', None))
                except Exception:
                    db_minutes = None

            if ENABLE_REDIS_CACHE:
                r = get_redis()
                if r is not None:
                    try:
                        r.setex(enabled_key, 60, '1' if enabled else '0')
                        if db_minutes is not None:
                            r.setex(minutes_key, 60, str(int(db_minutes)))
                    except Exception:
                        pass
        except Exception:
            enabled = True
            db_minutes = None

    if not enabled:
        return 0

    if db_minutes is not None:
        if db_minutes < 1:
            db_minutes = 1
        if db_minutes > 10080:
            db_minutes = 10080
        minutes = db_minutes

    return int(minutes) * 60


def _subject_from_payload(payload: Dict) -> Optional[Dict[str, object]]:
    if not payload:
        return None
    app_user_id = payload.get('app_user_id')
    if app_user_id:
        return {'user_type': 'app_user', 'user_id': int(app_user_id)}
    user_id = payload.get('user_id')
    if user_id:
        return {'user_type': 'user', 'user_id': int(user_id)}
    return None


def _activity_cache_key(user_type: str, user_id: int) -> str:
    return f'act:last:{user_type}:{user_id}'


def _get_last_activity(user_type: str, user_id: int) -> Optional[datetime]:
    if ENABLE_REDIS_CACHE:
        r = get_redis()
        if r is not None:
            try:
                raw = r.get(_activity_cache_key(user_type, user_id))
                if raw:
                    ts = int(raw)
                    return datetime.utcfromtimestamp(ts)
            except Exception:
                pass

    if not SessionActivity:
        return None
    try:
        row = SessionActivity.query.filter_by(user_type=user_type, user_id=user_id).first()
        return row.last_activity_at if row else None
    except Exception:
        return None


def _set_last_activity(user_type: str, user_id: int, when: datetime) -> None:
    timeout = _idle_timeout_seconds()
    if ENABLE_REDIS_CACHE:
        r = get_redis()
        if r is not None:
            try:
                ts = int(when.timestamp())
                ttl = max(timeout * 2, 3600) if timeout > 0 else 3600
                r.setex(_activity_cache_key(user_type, user_id), ttl, str(ts))
            except Exception:
                pass

    if not SessionActivity:
        return
    try:
        row = SessionActivity.query.filter_by(user_type=user_type, user_id=user_id).first()
        if not row:
            row = SessionActivity(user_type=user_type, user_id=user_id, last_activity_at=when, created_at=when, updated_at=when)
            db.session.add(row)
        else:
            row.last_activity_at = when
            row.updated_at = when
        db.session.commit()
    except Exception:
        db.session.rollback()


def _touch_last_activity_throttled(user_type: str, user_id: int) -> None:
    timeout = _idle_timeout_seconds()
    if timeout <= 0:
        return
    now = _now()
    last = _get_last_activity(user_type, user_id)
    # Reduce DB writes, but avoid a throttle that's >= the idle timeout.
    # If timeout is small (e.g. 60s), throttling at 60s can cause false expirations.
    throttle_seconds = 60
    if timeout <= 300:
        throttle_seconds = max(5, min(60, int(timeout // 4)))

    if last and (now - last).total_seconds() < throttle_seconds:
        return
    _set_last_activity(user_type, user_id, now)


def _revoke_user_refresh_tokens(user_type: str, user_id: int, reason: str = 'idle_timeout') -> None:
    if not RefreshToken:
        return
    try:
        (RefreshToken.query
         .filter_by(user_type=user_type, user_id=user_id, is_revoked=False)
         .update({
             'is_revoked': True,
             'revoked_at': _now(),
             'revoked_reason': reason,
         }, synchronize_session=False))
        db.session.commit()
    except Exception:
        db.session.rollback()


def _blacklist_access_token_best_effort(payload: Dict, reason: str) -> None:
    if not TokenBlacklist:
        return
    try:
        jti = payload.get('jti')
        exp = payload.get('exp')
        if not jti or not exp:
            return
        exp_dt = datetime.utcfromtimestamp(exp) if isinstance(exp, (int, float)) else None
        if not exp_dt:
            return

        exists = TokenBlacklist.query.filter_by(jti=jti).first()
        if not exists:
            db.session.add(TokenBlacklist(
                jti=jti,
                token_type='access',
                expires_at=exp_dt,
                reason=reason,
            ))
            db.session.commit()

        if ENABLE_REDIS_CACHE:
            r = get_redis()
            if r is not None:
                try:
                    ttl = int((exp_dt - _now()).total_seconds())
                    if ttl > 0:
                        r.setex(f'bl:jti:{jti}', ttl, '1')
                    else:
                        r.set(f'bl:jti:{jti}', '1')
                except Exception:
                    pass
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass


def _enforce_idle_timeout(payload: Dict) -> bool:
    """Return True if session is still valid; False if expired due to inactivity."""
    timeout = _idle_timeout_seconds()
    if timeout <= 0:
        return True

    subject = _subject_from_payload(payload or {})
    if not subject:
        return True

    user_type = subject['user_type']
    user_id = subject['user_id']
    now = _now()

    last = _get_last_activity(str(user_type), int(user_id))
    if last is None:
        # First-seen: initialize activity.
        _set_last_activity(str(user_type), int(user_id), now)
        return True

    if (now - last).total_seconds() > timeout:
        try:
            # Let downstream respond with a specific code.
            g.auth_error = 'session_expired'
        except Exception:
            pass
        _blacklist_access_token_best_effort(payload or {}, reason='idle_timeout')
        _revoke_user_refresh_tokens(str(user_type), int(user_id), reason='idle_timeout')
        return False

    # Valid session: refresh activity timestamp (throttled).
    _touch_last_activity_throttled(str(user_type), int(user_id))
    return True

def _get_jwt_secret() -> str:
    # في الإنتاج يجب ضبط JWT_SECRET_KEY. في التطوير نسمح بـ fallback لتجنب كسر التشغيل.
    secret = (JWT_SECRET_KEY or '').strip()
    if secret:
        return secret
    # fallback dev-only
    return (os.getenv('JWT_DEV_FALLBACK_SECRET') or JWT_DEV_FALLBACK_SECRET).strip()


def get_bearer_token() -> Optional[str]:
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return None
    return auth_header.split('Bearer ', 1)[1].strip() or None


def _is_blacklisted(jti: str) -> bool:
    if not jti or not TokenBlacklist:
        return False

    if ENABLE_REDIS_CACHE:
        r = get_redis()
        if r is not None:
            try:
                if r.get(f'bl:jti:{jti}'):
                    return True
            except Exception:
                # ignore redis failures and fall back to DB
                pass
    try:
        entry = TokenBlacklist.query.filter_by(jti=jti).first()
        if not entry:
            return False

        if ENABLE_REDIS_CACHE:
            r = get_redis()
            if r is not None:
                try:
                    ttl = None
                    if getattr(entry, 'expires_at', None):
                        ttl = int((entry.expires_at - datetime.utcnow()).total_seconds())
                    if ttl and ttl > 0:
                        r.setex(f'bl:jti:{jti}', ttl, '1')
                    else:
                        r.set(f'bl:jti:{jti}', '1')
                except Exception:
                    pass
        return True
    except Exception:
        # Fail closed: إذا تعذر التحقق، اعتبره محظور لحماية النظام
        return True


def generate_token(user, expires_in_minutes: Optional[int] = None):
    """إنشاء JWT access token للمستخدم.

    يدعم نوعين من الحسابات:
    - User (legacy)
    - AppUser (مرتبط بالموظفين)
    """
    now = datetime.utcnow()
    exp_minutes = expires_in_minutes if expires_in_minutes is not None else int(JWT_ACCESS_TOKEN_EXP_MINUTES)

    base_payload = {
        'username': getattr(user, 'username', None),
        'is_admin': getattr(user, 'is_admin', False),
        'exp': now + timedelta(minutes=exp_minutes),
        'iat': now,
        'jti': str(uuid.uuid4()),
    }

    if isinstance(user, AppUser):
        payload = {
            **base_payload,
            'app_user_id': user.id,
            'user_type': 'app_user',
        }
    else:
        payload = {
            **base_payload,
            'user_id': user.id,
            'user_type': 'user',
        }

    return jwt.encode(payload, _get_jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token):
    """
    فك تشفير JWT token
    
    Parameters:
    -----------
    token : str
        JWT token
    
    Returns:
    --------
    dict or None
        البيانات المُفككة أو None في حالة الفشل
    """
    try:
        payload = jwt.decode(token, _get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        jti = payload.get('jti')
        if jti and _is_blacklisted(jti):
            return None
        if not _enforce_idle_timeout(payload):
            return None
        return payload
    except jwt.ExpiredSignatureError:
        return None  # Token منتهي الصلاحية
    except jwt.InvalidTokenError:
        return None  # Token غير صالح


def decode_token_raw(token: str) -> Optional[Dict]:
    """Decode token بدون فحص blacklist (لاستخدامه في logout)."""
    try:
        return jwt.decode(token, _get_jwt_secret(), algorithms=[JWT_ALGORITHM])
    except Exception:
        return None


def get_current_user():
    """الحصول على المستخدم الحالي من token (يدعم User و AppUser)"""
    token = get_bearer_token()
    if not token:
        return None
    payload = decode_token(token)
    
    if not payload:
        return None
    
    # أولوية: app_user
    app_user_id = payload.get('app_user_id')
    if app_user_id:
        app_user = AppUser.query.get(app_user_id)
        if app_user and app_user.is_active:
            return app_user
    
    # ثانياً: user القديم
    user_id = payload.get('user_id')
    if user_id:
        user = User.query.get(user_id)
        if user and user.is_active:
            return user
    
    return None


def require_auth(f):
    """
    Decorator للتحقق من تسجيل الدخول
    
    Usage:
    ------
    @app.route('/protected')
    @require_auth
    def protected_route():
        user = g.current_user
        return {'message': f'Hello {user.username}'}
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 🔓 تعطيل مؤقت للـ auth في التطوير
        # التحقق من وجود current_user في g (من app.before_request)
        if hasattr(g, 'current_user') and g.current_user:
            return f(*args, **kwargs)
        
        user = get_current_user()
        
        if not user:
            auth_error = getattr(g, 'auth_error', None)
            if auth_error == 'session_expired':
                return jsonify({
                    'success': False,
                    'message': 'انتهت الجلسة بسبب عدم النشاط. الرجاء تسجيل الدخول مرة أخرى',
                    'error': 'session_expired'
                }), 401
            return jsonify({
                'success': False,
                'message': 'يجب تسجيل الدخول أولاً',
                'error': 'authentication_required'
            }), 401
        
        # حفظ المستخدم في g للوصول إليه في الدالة
        g.current_user = user
        
        # تحديث آخر تسجيل دخول (User.last_login / AppUser.last_login_at)
        now = datetime.utcnow()
        try:
            if hasattr(user, 'last_login_at'):
                last_login = user.last_login_at
                if not last_login or (now - last_login).seconds > 3600:
                    user.last_login_at = now
                    db.session.commit()
            elif hasattr(user, 'last_login'):
                last_login = user.last_login
                if not last_login or (now - last_login).seconds > 3600:
                    user.last_login = now
                    db.session.commit()
        except Exception:
            # لا نفشل الطلب بسبب تحديث last_login
            db.session.rollback()
        
        return f(*args, **kwargs)
    
    return decorated_function


def require_permission(permission_code):
    """
    Decorator للتحقق من صلاحية محددة
    
    Parameters:
    -----------
    permission_code : str
        كود الصلاحية المطلوبة (مثل: 'invoice.post')
    
    Usage:
    ------
    @app.route('/invoices/post/<int:id>')
    @require_permission('invoice.post')
    def post_invoice(id):
        # الكود هنا يُنفذ فقط إذا كان المستخدم لديه صلاحية invoice.post
        return {'message': 'Posted'}
    """
    def decorator(f):
        @wraps(f)
        @require_auth  # يجب تسجيل الدخول أولاً
        def decorated_function(*args, **kwargs):
            user = g.current_user
            
            # المدير الرئيسي لديه جميع الصلاحيات
            if user.is_admin:
                return f(*args, **kwargs)
            
            # التحقق من الصلاحية
            if not user.has_permission(permission_code):
                return jsonify({
                    'success': False,
                    'message': f'ليس لديك صلاحية لتنفيذ هذا الإجراء',
                    'error': 'permission_denied',
                    'required_permission': permission_code
                }), 403
            
            return f(*args, **kwargs)
        
        return decorated_function
    
    return decorator


def require_any_permission(*permission_codes):
    """
    Decorator للتحقق من امتلاك أي صلاحية من المُحددة
    
    Parameters:
    -----------
    *permission_codes : str
        أكواد الصلاحيات المطلوبة
    
    Usage:
    ------
    @app.route('/reports')
    @require_any_permission('report.view', 'report.financial')
    def view_reports():
        return {'reports': []}
    """
    def decorator(f):
        @wraps(f)
        @require_auth
        def decorated_function(*args, **kwargs):
            user = g.current_user
            
            # المدير الرئيسي لديه جميع الصلاحيات
            if user.is_admin:
                return f(*args, **kwargs)
            
            # التحقق من امتلاك أي صلاحية
            has_any = any(user.has_permission(code) for code in permission_codes)
            
            if not has_any:
                return jsonify({
                    'success': False,
                    'message': f'ليس لديك صلاحية لتنفيذ هذا الإجراء',
                    'error': 'permission_denied',
                    'required_permissions': list(permission_codes)
                }), 403
            
            return f(*args, **kwargs)
        
        return decorated_function
    
    return decorator


def require_admin(f):
    """
    Decorator للتحقق من كون المستخدم مدير
    
    Usage:
    ------
    @app.route('/admin/settings')
    @require_admin
    def admin_settings():
        return {'settings': {}}
    """
    @wraps(f)
    @require_auth
    def decorated_function(*args, **kwargs):
        user = g.current_user
        
        if not user.is_admin:
            return jsonify({
                'success': False,
                'message': 'هذه الصفحة متاحة للمديرين فقط',
                'error': 'admin_required'
            }), 403
        
        return f(*args, **kwargs)
    
    return decorated_function


def optional_auth(f):
    """
    Decorator اختياري للمصادقة - لا يفشل إذا لم يكن المستخدم مسجل دخول
    
    Usage:
    ------
    @app.route('/public-with-benefits')
    @optional_auth
    def public_route():
        user = g.get('current_user')  # قد يكون None
        if user:
            return {'message': f'Welcome back {user.username}'}
        return {'message': 'Welcome guest'}
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        g.current_user = user  # قد يكون None
        return f(*args, **kwargs)
    
    return decorated_function
