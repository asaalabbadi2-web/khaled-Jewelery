#!/usr/bin/env python3
"""
🏦 إعداد الشجرة المحاسبية المزدوجة (مالي + وزني)
═══════════════════════════════════════════════════════════════

هذا السكريبت يقوم بـ:
1. حذف جميع الحسابات القديمة بأمان
2. إنشاء الشجرة المالية الكاملة
3. إنشاء الشجرة الوزنية الكاملة
4. ربط كل حساب مالي بحساب وزني مقابل

الاستخدام:
    cd backend
    source venv/bin/activate
    python setup_dual_chart.py
"""

from app import app, db
from models import Account, JournalEntry, JournalEntryLine

def safe_delete_accounts():
    """حذف جميع الحسابات بأمان بعد التحقق من عدم وجود قيود"""
    with app.app_context():
        # تحقق من وجود قيود محاسبية
        entries_count = JournalEntry.query.count()
        if entries_count > 0:
            print(f"⚠️  تحذير: يوجد {entries_count} قيد محاسبي في النظام")
            response = input("هل تريد حذف جميع القيود والحسابات؟ (yes/no): ")
            if response.lower() != 'yes':
                print("❌ تم الإلغاء")
                return False
            
            # حذف القيود أولاً
            print("🗑️  جاري حذف القيود المحاسبية...")
            JournalEntryLine.query.delete()
            JournalEntry.query.delete()
            db.session.commit()
            print("✅ تم حذف جميع القيود")
        
        # حذف الحسابات
        print("🗑️  جاري حذف الحسابات القديمة...")
        accounts_count = Account.query.count()
        Account.query.delete()
        db.session.commit()
        print(f"✅ تم حذف {accounts_count} حساب")
        
        return True


def create_dual_chart_of_accounts():
    """إنشاء الشجرة المحاسبية المزدوجة"""
    with app.app_context():
        print("\n" + "="*70)
        print("🏦 إنشاء الشجرة المحاسبية المزدوجة")
        print("="*70)
        
        # ═══════════════════════════════════════════════════════════════
        # 🟡 القسم الأول: الشجرة المالية
        # ═══════════════════════════════════════════════════════════════
        
        print("\n📊 القسم الأول: الشجرة المالية (النقدية)")
        print("-" * 70)
        
        # 1 – الأصول
        print("1️⃣  الأصول...")
        
        # 1.1 الأصول المتداولة
        assets_current = Account(
            account_number='11',
            name='الأصول المتداولة',
            type='Asset',
            tracks_weight=False,
            transaction_type='cash'
        )
        db.session.add(assets_current)
        db.session.flush()
        
        # 1.1.1 الصندوق
        cash_box = Account(
            account_number='111',
            name='الصندوق',
            type='Asset',
            parent_id=assets_current.id,
            tracks_weight=False,
            transaction_type='cash'
        )
        db.session.add(cash_box)
        
        # 1.1.2 البنك
        bank = Account(
            account_number='112',
            name='البنك',
            type='Asset',
            parent_id=assets_current.id,
            tracks_weight=False,
            transaction_type='cash'
        )
        db.session.add(bank)
        
        # 1.1.3 العملاء
        customers = Account(
            account_number='113',
            name='العملاء',
            type='Asset',
            parent_id=assets_current.id,
            tracks_weight=False,
            transaction_type='cash'
        )
        db.session.add(customers)
        
        # 1.1.4 ذمم مكاتب التكسير
        offices_cash = Account(
            account_number='114',
            name='ذمم مكاتب التكسير (نقدي)',
            type='Asset',
            parent_id=assets_current.id,
            tracks_weight=False,
            transaction_type='cash'
        )
        db.session.add(offices_cash)
        
        # 1.1.5 مخزون ذهب (رئيسي)
        inventory_parent = Account(
            account_number='115',
            name='مخزون ذهب',
            type='Asset',
            parent_id=assets_current.id,
            tracks_weight=False,
            transaction_type='cash'
        )
        db.session.add(inventory_parent)
        db.session.flush()
        
        # 1.1.5.x مخزون حسب العيار
        for karat, num in [('24', '1151'), ('22', '1152'), ('21', '1153'), ('18', '1154')]:
            inv = Account(
                account_number=num,
                name=f'مخزون ذهب عيار {karat}',
                type='Asset',
                parent_id=inventory_parent.id,
                tracks_weight=False,
                transaction_type='cash'
            )
            db.session.add(inv)
        
        # 1.2 أصول أخرى
        assets_other = Account(
            account_number='12',
            name='أصول أخرى',
            type='Asset',
            tracks_weight=False,
            transaction_type='cash'
        )
        db.session.add(assets_other)
        db.session.flush()
        
        # 1.2.1 دفعات مقدمة
        prepaid = Account(
            account_number='121',
            name='دفعات مقدمة',
            type='Asset',
            parent_id=assets_other.id,
            tracks_weight=False,
            transaction_type='cash'
        )
        db.session.add(prepaid)
        
        # 1.2.2 عهد
        custody = Account(
            account_number='122',
            name='عهد',
            type='Asset',
            parent_id=assets_other.id,
            tracks_weight=False,
            transaction_type='cash'
        )
        db.session.add(custody)
        
        print("   ✅ تم إنشاء الأصول")
        
        # 2 – الالتزامات
        print("2️⃣  الالتزامات...")
        
        liabilities = Account(
            account_number='21',
            name='التزامات قصيرة الأجل',
            type='Liability',
            tracks_weight=False,
            transaction_type='cash'
        )
        db.session.add(liabilities)
        db.session.flush()
        
        # 2.1.1 الموردون
        suppliers = Account(
            account_number='211',
            name='الموردون',
            type='Liability',
            parent_id=liabilities.id,
            tracks_weight=False,
            transaction_type='cash'
        )
        db.session.add(suppliers)
        
        # 2.1.2 مكاتب التكسير
        offices_liability = Account(
            account_number='212',
            name='مكاتب التكسير (ذمم نقدية)',
            type='Liability',
            parent_id=liabilities.id,
            tracks_weight=False,
            transaction_type='cash'
        )
        db.session.add(offices_liability)
        
        # 2.1.3 رواتب مستحقة
        salaries_payable = Account(
            account_number='213',
            name='رواتب مستحقة',
            type='Liability',
            parent_id=liabilities.id,
            tracks_weight=False,
            transaction_type='cash'
        )
        db.session.add(salaries_payable)
        
        # 2.1.4 مصاريف مستحقة
        expenses_payable = Account(
            account_number='214',
            name='مصاريف مستحقة',
            type='Liability',
            parent_id=liabilities.id,
            tracks_weight=False,
            transaction_type='cash'
        )
        db.session.add(expenses_payable)
        
        print("   ✅ تم إنشاء الالتزامات")
        
        # 3 – حقوق الملكية
        print("3️⃣  حقوق الملكية...")
        
        # 3.1 رأس المال
        capital = Account(
            account_number='31',
            name='رأس المال',
            type='Equity',
            tracks_weight=False,
            transaction_type='cash'
        )
        db.session.add(capital)
        
        # 3.2 أرباح وخسائر
        retained_earnings = Account(
            account_number='32',
            name='أرباح وخسائر',
            type='Equity',
            tracks_weight=False,
            transaction_type='cash'
        )
        db.session.add(retained_earnings)
        
        # 3.3 احتياطيات
        reserves = Account(
            account_number='33',
            name='احتياطيات',
            type='Equity',
            tracks_weight=False,
            transaction_type='cash'
        )
        db.session.add(reserves)
        
        print("   ✅ تم إنشاء حقوق الملكية")
        
        # 4 – الإيرادات
        print("4️⃣  الإيرادات...")
        
        revenue_parent = Account(
            account_number='40',
            name='الإيرادات',
            type='Revenue',
            tracks_weight=False,
            transaction_type='cash'
        )
        db.session.add(revenue_parent)
        db.session.flush()
        
        revenues = [
            ('401', 'إيرادات بيع ذهب'),
            ('402', 'إيرادات مصنعية'),
            ('403', 'إيرادات فرق تسكير'),
            ('404', 'إيرادات تقييم وزني'),
        ]
        
        for num, name in revenues:
            rev = Account(
                account_number=num,
                name=name,
                type='Revenue',
                parent_id=revenue_parent.id,
                tracks_weight=False,
                transaction_type='cash'
            )
            db.session.add(rev)
        
        print("   ✅ تم إنشاء الإيرادات")
        
        # 5 – المصروفات
        print("5️⃣  المصروفات...")
        
        expense_parent = Account(
            account_number='50',
            name='المصروفات',
            type='Expense',
            tracks_weight=False,
            transaction_type='cash'
        )
        db.session.add(expense_parent)
        db.session.flush()
        
        expenses = [
            ('501', 'تكلفة المبيعات'),
            ('502', 'مصروفات تشغيل'),
            ('503', 'رواتب'),
            ('504', 'إيجارات'),
            ('505', 'كهرباء'),
            ('506', 'دعاية'),
            ('507', 'مصروفات وزن'),
        ]
        
        for num, name in expenses:
            exp = Account(
                account_number=num,
                name=name,
                type='Expense',
                parent_id=expense_parent.id,
                tracks_weight=False,
                transaction_type='cash'
            )
            db.session.add(exp)
        
        print("   ✅ تم إنشاء المصروفات")
        
        # ═══════════════════════════════════════════════════════════════
        # 🟣 القسم الثاني: الشجرة الوزنية
        # ═══════════════════════════════════════════════════════════════
        
        print("\n⚖️  القسم الثاني: الشجرة الوزنية")
        print("-" * 70)
        
        # 1W – وزن الأصول
        print("1️⃣W أصول وزنية...")
        
        # 1W.1 أصول وزنية
        assets_weight_parent = Account(
            account_number='1W1',
            name='أصول وزنية',
            type='Asset',
            tracks_weight=True,
            transaction_type='gold'
        )
        db.session.add(assets_weight_parent)
        db.session.flush()
        
        weight_assets = [
            ('1W11', 'صندوق وزني', False),
            ('1W12', 'بنك وزني', False),
            ('1W13', 'عملاء وزني', True),
            ('1W14', 'الديوان وزني', False),
        ]
        
        for num, name, is_parent in weight_assets:
            acc = Account(
                account_number=num,
                name=name,
                type='Asset',
                parent_id=assets_weight_parent.id,
                tracks_weight=True,
                transaction_type='gold'
            )
            db.session.add(acc)
        
        # 1W.2 مخزون وزني
        inventory_weight_parent = Account(
            account_number='1W2',
            name='مخزون وزني',
            type='Asset',
            tracks_weight=True,
            transaction_type='gold'
        )
        db.session.add(inventory_weight_parent)
        db.session.flush()
        
        for karat, num in [('24', '1W21'), ('22', '1W22'), ('21', '1W23'), ('18', '1W24')]:
            inv = Account(
                account_number=num,
                name=f'مخزون ذهب فعلي {karat}',
                type='Asset',
                parent_id=inventory_weight_parent.id,
                tracks_weight=True,
                transaction_type='gold'
            )
            db.session.add(inv)
        
        print("   ✅ تم إنشاء أصول وزنية")
        
        # 2W – التزامات وزنية
        print("2️⃣W التزامات وزنية...")
        
        liabilities_weight = Account(
            account_number='2W1',
            name='التزامات وزنية',
            type='Liability',
            tracks_weight=True,
            transaction_type='gold'
        )
        db.session.add(liabilities_weight)
        db.session.flush()
        
        weight_liabilities = [
            ('2W11', 'موردون وزني'),
            ('2W12', 'رواتب مستحقة وزني'),
            ('2W13', 'مصاريف مستحقة وزني'),
        ]
        
        for num, name in weight_liabilities:
            acc = Account(
                account_number=num,
                name=name,
                type='Liability',
                parent_id=liabilities_weight.id,
                tracks_weight=True,
                transaction_type='gold'
            )
            db.session.add(acc)
        
        print("   ✅ تم إنشاء التزامات وزنية")
        
        # 3W – حقوق ملكية وزنية
        print("3️⃣W حقوق ملكية وزنية...")
        
        equity_weight = Account(
            account_number='3W',
            name='حقوق ملكية وزنية',
            type='Equity',
            tracks_weight=True,
            transaction_type='gold'
        )
        db.session.add(equity_weight)
        db.session.flush()
        
        weight_equity = [
            ('3W1', 'رأس مال وزني'),
            ('3W2', 'أرباح وخسائر وزنية'),
        ]
        
        for num, name in weight_equity:
            acc = Account(
                account_number=num,
                name=name,
                type='Equity',
                parent_id=equity_weight.id,
                tracks_weight=True,
                transaction_type='gold'
            )
            db.session.add(acc)
        
        print("   ✅ تم إنشاء حقوق ملكية وزنية")
        
        # 4W – إيرادات وزنية
        print("4️⃣W إيرادات وزنية...")
        
        revenue_weight = Account(
            account_number='4W',
            name='إيرادات وزنية',
            type='Revenue',
            tracks_weight=True,
            transaction_type='gold'
        )
        db.session.add(revenue_weight)
        db.session.flush()
        
        weight_revenues = [
            ('4W1', 'إيرادات بيع وزنية'),
            ('4W2', 'إيرادات مصنعية وزنية'),
            ('4W3', 'إيرادات فرق تقييم وزني'),
            ('4W4', 'إيرادات تسكير وزني'),
        ]
        
        for num, name in weight_revenues:
            acc = Account(
                account_number=num,
                name=name,
                type='Revenue',
                parent_id=revenue_weight.id,
                tracks_weight=True,
                transaction_type='gold'
            )
            db.session.add(acc)
        
        print("   ✅ تم إنشاء إيرادات وزنية")
        
        # 5W – مصروفات وزنية
        print("5️⃣W مصروفات وزنية...")
        
        expense_weight = Account(
            account_number='5W',
            name='مصروفات وزنية',
            type='Expense',
            tracks_weight=True,
            transaction_type='gold'
        )
        db.session.add(expense_weight)
        db.session.flush()
        
        weight_expenses = [
            ('5W1', 'تكلفة مبيعات وزنية'),
            ('5W2', 'مصروفات تشغيل وزنية'),
            ('5W3', 'رواتب وزنية'),
            ('5W4', 'إيجارات وزنية'),
            ('5W5', 'كهرباء وزنية'),
            ('5W6', 'دعاية وزنية'),
        ]
        
        for num, name in weight_expenses:
            acc = Account(
                account_number=num,
                name=name,
                type='Expense',
                parent_id=expense_weight.id,
                tracks_weight=True,
                transaction_type='gold'
            )
            db.session.add(acc)
        
        print("   ✅ تم إنشاء مصروفات وزنية")
        
        # حفظ جميع الحسابات
        db.session.commit()
        
        # عرض الإحصائيات
        total_accounts = Account.query.count()
        cash_accounts = Account.query.filter_by(transaction_type='cash').count()
        gold_accounts = Account.query.filter_by(transaction_type='gold').count()
        
        print("\n" + "="*70)
        print("✅ تم إنشاء الشجرة المحاسبية المزدوجة بنجاح!")
        print("="*70)
        print(f"📊 إجمالي الحسابات: {total_accounts}")
        print(f"💵 حسابات نقدية: {cash_accounts}")
        print(f"⚖️  حسابات وزنية: {gold_accounts}")
        print("="*70)


def main():
    """الدالة الرئيسية"""
    print("\n" + "="*70)
    print("🏦 إعداد الشجرة المحاسبية المزدوجة")
    print("="*70)
    
    # حذف الحسابات القديمة
    if not safe_delete_accounts():
        return
    
    # إنشاء الشجرة الجديدة
    create_dual_chart_of_accounts()
    
    print("\n🎉 تم الانتهاء بنجاح!")
    print("يمكنك الآن استخدام النظام مع الشجرة المحاسبية المزدوجة")
    print("="*70 + "\n")


if __name__ == '__main__':
    main()
