"""
تحديث cache حسابات الشجرة المزدوجة في الذاكرة
يتم تشغيله عند بدء التطبيق أو بعد تحديث الحسابات
"""

from flask import current_app
from models import Account, db


def refresh_account_cache():
    """
    تحديث الـ cache للبحث السريع عن الحسابات
    """
    from routes import _ACCOUNT_NUMBER_CACHE
    
    # مسح الـ cache القديم
    _ACCOUNT_NUMBER_CACHE.clear()
    
    # جلب جميع الحسابات وإضافتها للـ cache
    all_accounts = Account.query.all()
    
    for account in all_accounts:
        if account.account_number:
            _ACCOUNT_NUMBER_CACHE[str(account.account_number)] = account.id
    
    print(f"✅ تم تحديث cache الحسابات: {len(_ACCOUNT_NUMBER_CACHE)} حساب")
    return len(_ACCOUNT_NUMBER_CACHE)


def preload_critical_accounts():
    """
    تحميل الحسابات الحرجة مسبقاً
    """
    from routes import get_account_id_by_number
    
    # NOTE: This list must match the latest dual chart created by `setup_dual_chart.py`.
    critical_accounts = [
        # الشجرة المالية (cash)
        '11',
        '111',
        '112',
        '113',
        '114',
        '115',
        '1151',
        '1152',
        '1153',
        '1154',
        '12',
        '121',
        '122',
        '21',
        '211',
        '212',
        '213',
        '214',
        '31',
        '32',
        '33',
        '40',
        '401',
        '402',
        '403',
        '404',
        '50',
        '501',
        '502',
        '503',
        '504',
        '505',
        '506',
        '507',

        # الشجرة الوزنية (gold)
        '1W1',
        '1W11',
        '1W12',
        '1W13',
        '1W14',
        '1W2',
        '1W21',
        '1W22',
        '1W23',
        '1W24',
        '2W1',
        '2W11',
        '2W12',
        '2W13',
        '3W',
        '3W1',
        '3W2',
        '4W',
        '4W1',
        '4W2',
        '4W3',
        '4W4',
        '5W',
        '5W1',
        '5W2',
        '5W3',
        '5W4',
        '5W5',
        '5W6',
    ]
    
    loaded = 0
    missing = []
    
    for acc_number in critical_accounts:
        acc_id = get_account_id_by_number(acc_number)
        if acc_id:
            loaded += 1
        else:
            missing.append(acc_number)
    
    if missing:
        print(f"⚠️  الحسابات المفقودة: {', '.join(missing)}")
    
    print(f"✅ تم تحميل {loaded}/{len(critical_accounts)} حساب حرج")
    return loaded, missing


def verify_dual_tree_integrity():
    """
    التحقق من سلامة الشجرة المزدوجة
    """
    issues = []
    
    # التحقق من وجود الحسابات الأساسية للشجرة المالية/الوزنية حسب الشجرة المزدوجة الجديدة
    cash_required = [
        '11',
        '12',
        '21',
        '31',
        '32',
        '33',
        '40',
        '50',
        # Key leaf accounts
        '111',
        '112',
        '113',
        '1153',
        '211',
        '401',
        '501',
    ]
    for num in cash_required:
        acc = Account.query.filter_by(account_number=num, transaction_type='cash').first()
        if not acc:
            issues.append(f"الحساب المالي {num} مفقود")

    gold_required = [
        '1W1',
        '1W2',
        '2W1',
        '3W',
        '4W',
        '5W',
        # Key leaf accounts
        '1W11',
        '1W13',
        '1W23',
        '2W11',
        '4W1',
        '5W1',
    ]
    for num in gold_required:
        acc = Account.query.filter_by(account_number=num, transaction_type='gold').first()
        if not acc:
            issues.append(f"الحساب الوزني {num} مفقود")
    
    # التحقق من عدد الحسابات
    cash_count = Account.query.filter_by(transaction_type='cash').count()
    gold_count = Account.query.filter_by(transaction_type='gold').count()
    
    print(f"📊 إحصائيات الشجرة المزدوجة:")
    print(f"   - حسابات مالية (cash): {cash_count}")
    print(f"   - حسابات مذكرة (gold): {gold_count}")
    print(f"   - إجمالي: {cash_count + gold_count}")
    
    if issues:
        print(f"\n⚠️  مشاكل في الشجرة المزدوجة ({len(issues)}):")
        for issue in issues:
            print(f"   - {issue}")
        return False
    else:
        print("✅ الشجرة المزدوجة سليمة ومتكاملة")
        return True


if __name__ == '__main__':
    from app import app
    
    with app.app_context():
        print("=" * 60)
        print("🔄 تحديث Cache الحسابات")
        print("=" * 60)
        
        # 1. تحديث الـ cache
        cache_size = refresh_account_cache()
        
        # 2. تحميل الحسابات الحرجة
        loaded, missing = preload_critical_accounts()
        
        # 3. التحقق من سلامة الشجرة
        is_valid = verify_dual_tree_integrity()
        
        print("=" * 60)
        if is_valid and not missing:
            print("✅ جميع الخطوات نجحت - النظام جاهز!")
        else:
            print("⚠️  هناك مشاكل تحتاج إلى حل")
        print("=" * 60)
