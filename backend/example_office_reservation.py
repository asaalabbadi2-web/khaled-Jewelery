"""
مثال عملي: تسجيل حجز ذهب من مكتب تسكير في النظام المزدوج
"""

from app import app
from dual_system_helpers import create_dual_entry_with_memo, get_live_gold_price_helper
from models import db, Office, OfficeReservation
from datetime import datetime

def create_office_reservation_example():
    """
    مثال: حجز 100 جرام عيار 21 من مكتب تسكير
    المبلغ المدفوع: 40,000 ريال
    """
    with app.app_context():
        # 1. الحصول على سعر الذهب الحالي
        gold_price = get_live_gold_price_helper()
        print(f'📊 سعر الذهب الحالي: {gold_price} ريال/جرام')
        print()
        
        # 2. تفاصيل الحجز
        reserved_weight = 100.0  # جرام عيار 21
        paid_amount = 40000.0    # ريال
        office_name = "مكتب الذهب الملكي"
        
        print('📋 تفاصيل الحجز:')
        print(f'   الوزن المحجوز: {reserved_weight} جرام (عيار 21)')
        print(f'   المبلغ المدفوع: {paid_amount:,.2f} ريال')
        print(f'   المكتب: {office_name}')
        print()
        
        # 3. إنشاء القيد المزدوج
        print('🔥 إنشاء القيد المزدوج...')
        print()
        
        entry = create_dual_entry_with_memo(
            date=datetime.now(),
            description=f'حجز ذهب من {office_name} - {reserved_weight}g',
            entries=[
                {
                    'account_code': '1290',      # جسر مشتريات الذهب
                    'debit': paid_amount,        # مدين نقدي
                    'debit_weight': reserved_weight  # مدين وزني
                },
                {
                    'account_code': '21110',     # مكاتب التسكير
                    'credit': paid_amount,       # دائن نقدي
                    'credit_weight': reserved_weight  # دائن وزني
                }
            ],
            reference_type='office_reservation',
            reference_id=1,
            gold_price=gold_price,
            posted=True  # ترحيل مباشر
        )
        
        db.session.commit()
        
        # 4. عرض النتيجة
        print('=' * 80)
        print(f'✅ تم إنشاء القيد رقم: {entry.entry_number}')
        print(f'   الوصف: {entry.description}')
        print(f'   عدد السطور: {len(entry.lines)} سطر')
        print('=' * 80)
        print()
        
        # 5. تفصيل السطور
        for i, line in enumerate(entry.lines, 1):
            account_type = '(حساب مذكرة)' if line.account.account_number.startswith('7') else '(حساب مالي)'
            print(f'{i}. [{line.account.account_number}] {line.account.name} {account_type}')
            
            if line.cash_debit > 0:
                print(f'   💰 مدين نقدي: {line.cash_debit:,.2f} ريال')
            if line.cash_credit > 0:
                print(f'   💰 دائن نقدي: {line.cash_credit:,.2f} ريال')
            if line.debit_weight > 0:
                print(f'   ⚖️  مدين وزن: {line.debit_weight:.4f} جرام')
            if line.credit_weight > 0:
                print(f'   ⚖️  دائن وزن: {line.credit_weight:.4f} جرام')
            if line.gold_price_snapshot:
                print(f'   💵 سعر الذهب: {line.gold_price_snapshot:,.2f} ريال/جرام')
            print()
        
        print('=' * 80)
        print('📊 الخلاصة:')
        print('=' * 80)
        print('✅ تم تسجيل حجز الذهب بنجاح في النظام المزدوج')
        print('✅ القيد المالي: يسجل المبلغ النقدي (40,000 ريال)')
        print('✅ قيد المذكرة: يسجل الوزن المعادل (100 جرام)')
        print('✅ تم حفظ snapshot لسعر الذهب وقت المعاملة')
        print()
        print('📌 الحسابات المتأثرة:')
        print('   1290 (جسر مشتريات) ← زاد بـ 40,000 ريال + 100g')
        print('   71290 (جسر مشتريات وزن) ← زاد بـ 100g')
        print('   21110 (مكاتب التسكير) ← زاد بـ 40,000 ريال + 100g')
        print('   72110 (مكاتب التسكير وزن) ← زاد بـ 100g')
        print()
        
        return entry

if __name__ == '__main__':
    entry = create_office_reservation_example()
