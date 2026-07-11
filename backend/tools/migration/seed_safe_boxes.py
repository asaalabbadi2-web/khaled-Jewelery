#!/usr/bin/env python3
"""
إنشاء الخزائن الافتراضية
"""
import os
import sys

from sqlalchemy import or_

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import app
from models import db, SafeBox, Account


def seed_safe_boxes():
    """إنشاء الخزائن الافتراضية"""
    with app.app_context():
        print("🔄 بدء إنشاء الخزائن الافتراضية...")
        
        # البحث عن الحسابات
        accounts = {
            'cash_main': Account.query.filter(
                or_(
                    Account.account_number == '1100',
                    Account.name.like('%صندوق النقدية%'),
                    Account.name.like('%الصندوق الرئيسي%')
                )
            ).first(),
            'bank_riyadh': Account.query.filter(
                or_(
                    Account.account_number == '1136',
                    Account.name.like('%بنك الرياض%')
                )
            ).first(),
            'bank_rajhi': Account.query.filter(
                or_(
                    Account.account_number == '1120',
                    Account.name.like('%بنك الراجحي%')
                )
            ).first(),
            'bank_ahli': Account.query.filter(
                or_(
                    Account.account_number == '1110',
                    Account.name.like('%البنك الأهلي%')
                )
            ).first(),
        }
        
        # البحث عن حسابات الذهب (يمكن إضافتها لاحقاً)
        gold_accounts = {
            18: Account.query.filter(Account.name.like('%عيار 18%')).first(),
            21: Account.query.filter(Account.name.like('%عيار 21%')).first(),
            22: Account.query.filter(Account.name.like('%عيار 22%')).first(),
            24: Account.query.filter(Account.name.like('%عيار 24%')).first(),
        }
        
        safe_boxes = []
        
        # 1. خزينة النقدية الرئيسية
        if accounts['cash_main']:
            if not SafeBox.query.filter_by(name='صندوق النقدية الرئيسي').first():
                safe_boxes.append(SafeBox(
                    name='صندوق النقدية الرئيسي',
                    name_en='Main Cash Box',
                    safe_type='cash',
                    account_id=accounts['cash_main'].id,
                    is_active=True,
                    is_default=True,
                    notes='الصندوق النقدي الرئيسي للمحل',
                    created_by='system'
                ))
        
        # 2. خزائن البنوك
        if accounts['bank_riyadh']:
            if not SafeBox.query.filter_by(name='بنك الرياض').first():
                safe_boxes.append(SafeBox(
                    name='بنك الرياض',
                    name_en='Riyad Bank',
                    safe_type='bank',
                    account_id=accounts['bank_riyadh'].id,
                    bank_name='بنك الرياض',
                    is_active=True,
                    is_default=True,  # البنك الافتراضي
                    notes='الحساب البنكي الرئيسي',
                    created_by='system'
                ))
        
        if accounts['bank_rajhi']:
            if not SafeBox.query.filter_by(name='مصرف الراجحي').first():
                safe_boxes.append(SafeBox(
                    name='مصرف الراجحي',
                    name_en='Al Rajhi Bank',
                    safe_type='bank',
                    account_id=accounts['bank_rajhi'].id,
                    bank_name='مصرف الراجحي',
                    is_active=True,
                    is_default=False,
                    notes='حساب بنكي ثانوي',
                    created_by='system'
                ))
        
        if accounts['bank_ahli']:
            if not SafeBox.query.filter_by(name='البنك الأهلي').first():
                safe_boxes.append(SafeBox(
                    name='البنك الأهلي',
                    name_en='Al Ahli Bank',
                    safe_type='bank',
                    account_id=accounts['bank_ahli'].id,
                    bank_name='البنك الأهلي التجاري',
                    is_active=True,
                    is_default=False,
                    notes='حساب بنكي ثانوي',
                    created_by='system'
                ))
        
        # 3. خزينة الذهب (موحّدة متعددة العيارات)
        # في النظام الموحّد: خزينة ذهب واحدة تحمل كل العيارات داخل نفس الحساب (tracks_weight=True)
        gold_account = gold_accounts.get(21) or gold_accounts.get(24) or gold_accounts.get(22) or gold_accounts.get(18)
        if gold_account:
            unified_name = 'صندوق الذهب (متعدد العيارات)'
            if not SafeBox.query.filter_by(safe_type='gold', karat=None).first():
                safe_boxes.append(SafeBox(
                    name=unified_name,
                    name_en='Unified Gold Box',
                    safe_type='gold',
                    account_id=gold_account.id,
                    karat=None,
                    is_active=True,
                    is_default=True,
                    notes='خزينة ذهب واحدة متعددة العيارات (18/21/22/24)',
                    created_by='system'
                ))
        
        # حفظ جميع الخزائن
        if safe_boxes:
            db.session.add_all(safe_boxes)
            db.session.commit()
            print(f"✅ تم إنشاء {len(safe_boxes)} خزينة بنجاح:")
            for sb in safe_boxes:
                print(f"   - {sb.name} ({sb.safe_type})")
        else:
            print("⚠️ لم يتم إنشاء أي خزائن (قد تكون موجودة مسبقاً)")
        
        # عرض جميع الخزائن
        all_safes = SafeBox.query.all()
        print(f"\n📦 إجمالي الخزائن: {len(all_safes)}")
        for sb in all_safes:
            default_str = "⭐ افتراضي" if sb.is_default else ""
            active_str = "✅" if sb.is_active else "❌"
            print(f"   {active_str} {sb.name} ({sb.safe_type}) {default_str}")

if __name__ == '__main__':
    seed_safe_boxes()
