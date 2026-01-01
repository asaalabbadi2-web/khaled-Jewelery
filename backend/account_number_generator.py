"""
Account Number Generator - مولد أرقام الحسابات التلقائي

هذا الملف يحتوي على دوال مساعدة لتوليد أرقام الحسابات بشكل تلقائي
يدعم:
- الترقيم المتصل (للعملاء والموردين بالآلاف)
- الترقيم مع التباعد (للحسابات العادية)
"""

from models import Account, db


def _digits_only(value: str) -> str:
    return ''.join(ch for ch in str(value or '').strip() if ch.isdigit())


def _compute_child_range_and_step(parent_account_number: str) -> tuple[int, int, int, int]:
    """Return (start, end, step, child_len) for the next-level children of a parent.

    قواعد الترقيم المعتمدة (مطابقة للشجرة الحالية):
    - أب 1 خانة (1/2/3/..): أبناء خانتين 11..19 (خطوة 1)
    - أب خانتين (11/12/..): أبناء 3 خانات 110..190 (خطوة 10)
    - أب 3 خانات (110/120/..): أبناء 4 خانات 1100..1190 (خطوة 10)
    - أب 4 خانات (مثل 1200/1300): أبناء تفصيلية 7 خانات 1200000..1200999 (خطوة 1)
    - أطوال أخرى: افتراضي إضافة خانة واحدة (خطوة 1)
    """

    parent_digits = _digits_only(parent_account_number)
    if not parent_digits:
        raise ValueError('رقم الحساب الأب غير صالح')

    parent_len = len(parent_digits)
    parent_int = int(parent_digits)

    if parent_len == 1:
        # 1 -> 11..19
        start = parent_int * 10 + 1
        end = parent_int * 10 + 9
        return start, end, 1, 2

    if parent_len == 2:
        # 11 -> 110..190 (10)
        # (9 slots: 110, 120, ..., 190)
        start = parent_int * 10
        end = start + 80
        return start, end, 10, 3

    if parent_len == 3:
        # 110 -> 1100..1190 (10)
        start = parent_int * 10
        end = start + 90
        return start, end, 10, 4

    if parent_len == 4:
        # 1200 -> 1200000..1200999 (تفصيلي)
        start = parent_int * 1000
        end = start + 999
        return start, end, 1, 7

    # fallback: one extra digit
    start = parent_int * 10
    end = start + 9
    return start, end, 1, parent_len + 1


def get_next_account_number(parent_account_number: str, use_spacing: bool = False) -> str:
    """
    توليد رقم الحساب التالي المتاح لحساب فرعي
    
    Args:
        parent_account_number (str): رقم الحساب الأب (مثل '1100' لعملاء بيع الذهب)
        use_spacing (bool): إذا كان True، استخدم تباعد 10، وإلا استخدم ترقيم متصل (1,2,3...)
    
    Returns:
        str: رقم الحساب التالي المتاح
        
    Raises:
        ValueError: إذا تجاوزت السعة المتاحة للنطاق
        
    Examples:
        >>> get_next_account_number('1100', use_spacing=False)
        '110000'  # أول عميل بيع ذهب
        
        >>> get_next_account_number('1100', use_spacing=False)
        '110001'  # ثاني عميل بيع ذهب
        
        >>> get_next_account_number('100', use_spacing=True)
        '1040'  # رابع حساب بنكي (بعد 1000, 1010, 1020, 1030)
    """
    
    start_range, end_range, step, _child_len = _compute_child_range_and_step(parent_account_number)
    
    # ابحث عن آخر رقم حساب مستخدم في هذا النطاق
    last_account = Account.query.filter(
        db.cast(Account.account_number, db.Integer) >= start_range,
        db.cast(Account.account_number, db.Integer) <= end_range
    ).order_by(db.cast(Account.account_number, db.Integer).desc()).first()
    
    if last_account:
        last_number = int(last_account.account_number)
        next_number = last_number + step
    else:
        # أول حساب في هذا النطاق
        next_number = start_range
    
    # تحقق من عدم تجاوز النطاق المسموح
    if next_number > end_range:
        raise ValueError(
            f"تجاوزت السعة المتاحة للحساب {parent_account_number}. "
            f"النطاق المسموح: {start_range} - {end_range}"
        )
    
    return str(next_number)


def get_customer_account_capacity(customer_category: str = '1200') -> dict:
    """
    احصل على معلومات السعة المتاحة لفئة عملاء معينة
    
    Args:
        customer_category (str): رقم فئة العملاء (1100، 1110، 1120...)
        
    Returns:
        dict: معلومات السعة والاستخدام
        
    Example:
        >>> get_customer_account_capacity('1100')
        {
            'total_capacity': 10000,
            'used': 150,
            'available': 9850,
            'next_number': '110150',
            'usage_percentage': 1.5
        }
    """
    
    start_range, end_range, _step, _child_len = _compute_child_range_and_step(customer_category)
    
    total_capacity = end_range - start_range + 1
    
    # عدد الحسابات المستخدمة
    used_count = Account.query.filter(
        db.cast(Account.account_number, db.Integer) >= start_range,
        db.cast(Account.account_number, db.Integer) <= end_range
    ).count()
    
    available = total_capacity - used_count
    
    # احصل على الرقم التالي
    try:
        next_number = get_next_account_number(customer_category, use_spacing=False)
    except ValueError:
        next_number = None
    
    usage_percentage = (used_count / total_capacity) * 100
    
    return {
        'category': customer_category,
        'total_capacity': total_capacity,
        'used': used_count,
        'available': available,
        'next_number': next_number,
        'usage_percentage': round(usage_percentage, 2),
        'start_range': start_range,
        'end_range': end_range
    }


def suggest_account_number_with_validation(parent_account_number: str) -> dict:
    """
    اقترح رقم الحساب التالي مع التحقق من الصحة
    
    Args:
        parent_account_number (str): رقم الحساب الأب
        
    Returns:
        dict: الرقم المقترح ومعلومات إضافية
        
    Example:
        >>> suggest_account_number_with_validation('1100')
        {
            'suggested_number': '110000',
            'is_valid': True,
            'message': 'رقم الحساب متاح',
            'capacity_info': {...}
        }
    """
    
    try:
        start_range, end_range, step, child_len = _compute_child_range_and_step(parent_account_number)

        use_spacing = step == 10
        suggested_number = get_next_account_number(parent_account_number, use_spacing=use_spacing)

        capacity_info = None
        # التفصيلي تحت 4 خانات (مثل 1200/1210/1300..): أرجع معلومات السعة
        if child_len == 7:
            capacity_info = get_customer_account_capacity(parent_account_number)
        
        return {
            'suggested_number': suggested_number,
            'is_valid': True,
            'message': 'رقم الحساب متاح',
            'use_spacing': use_spacing,
            'capacity_info': capacity_info,
            'range': {
                'start': start_range,
                'end': end_range,
                'step': step,
                'child_len': child_len,
            },
        }
        
    except ValueError as e:
        return {
            'suggested_number': None,
            'is_valid': False,
            'message': str(e),
            'use_spacing': use_spacing,
            'capacity_info': None
        }


def validate_account_number(account_number: str, parent_account_number: str) -> dict:
    """
    التحقق من صحة رقم حساب مقترح
    
    Args:
        account_number (str): رقم الحساب المقترح
        parent_account_number (str): رقم الحساب الأب
        
    Returns:
        dict: نتيجة التحقق
        
    Example:
        >>> validate_account_number('110000', '1100')
        {'is_valid': True, 'message': 'رقم الحساب صحيح ومتاح'}
    """
    
    acc_digits = _digits_only(account_number)
    parent_digits = _digits_only(parent_account_number)

    if not acc_digits or not parent_digits:
        return {'is_valid': False, 'message': 'رقم الحساب غير صالح'}

    # تحقق من أن الرقم غير مستخدم
    existing = Account.query.filter_by(account_number=acc_digits).first()
    if existing:
        return {
            'is_valid': False,
            'message': f'رقم الحساب {acc_digits} مستخدم بالفعل'
        }

    # تحقق من النطاق/الطول/الخطوة وفق القاعدة
    start, end, step, child_len = _compute_child_range_and_step(parent_digits)
    account_num = int(acc_digits)

    if len(acc_digits) != child_len:
        return {
            'is_valid': False,
            'message': f'طول رقم الحساب غير صحيح. المتوقع {child_len} خانات'
        }
    
    if account_num < start or account_num > end:
        return {
            'is_valid': False,
            'message': f'رقم الحساب خارج النطاق المسموح للحساب الأب ({start} - {end})'
        }

    if (account_num - start) % step != 0:
        return {
            'is_valid': False,
            'message': f'رقم الحساب لا يتبع قاعدة الترقيم (الخطوة {step})'
        }
    
    return {
        'is_valid': True,
        'message': 'رقم الحساب صحيح ومتاح'
    }


if __name__ == '__main__':
    # اختبار الدوال
    from app import app
    
    with app.app_context():
        # مثال 1: عملاء بيع ذهب
        print("=== عملاء بيع ذهب ===")
        result = suggest_account_number_with_validation('1100')
        print(f"الرقم المقترح: {result['suggested_number']}")
        if result['capacity_info']:
            print(f"السعة المستخدمة: {result['capacity_info']['used']} / {result['capacity_info']['total_capacity']}")
            print(f"نسبة الاستخدام: {result['capacity_info']['usage_percentage']}%")
        
        print("\n=== حسابات بنكية ===")
        result = suggest_account_number_with_validation('100')
        print(f"الرقم المقترح للبنك الجديد: {result['suggested_number']}")
        print(f"استخدام التباعد: {result['use_spacing']}")
