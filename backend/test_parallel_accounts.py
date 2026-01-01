#!/usr/bin/env python3
"""
اختبار نظام إنشاء الحسابات الموازية تلقائياً
==============================================

يختبر:
1. إضافة حساب مالي → إنشاء حساب وزني تلقائياً
2. إضافة حساب وزني → إنشاء حساب مالي تلقائياً
3. الربط التلقائي عبر memo_account_id
"""

from app import app, db
from models import Account
import requests
import json

def test_via_api():
    """اختبار عبر API"""
    print("\n" + "=" * 70)
    print("🧪 اختبار إنشاء الحسابات الموازية عبر API")
    print("=" * 70)
    
    base_url = "http://127.0.0.1:8001/api"
    
    # 1. إضافة حساب مالي
    print("\n1️⃣ إضافة حساب مالي جديد...")
    financial_account = {
        "account_number": "1150",
        "name": "بنك الإنماء",
        "type": "Asset",
        "transaction_type": "cash",
        "parent_id": None,
        "tracks_weight": False
    }
    
    response = requests.post(f"{base_url}/accounts", json=financial_account)
    print(f"   Status: {response.status_code}")
    
    if response.status_code == 201:
        result = response.json()
        print(f"   ✅ تم إنشاء الحساب: {result['account_number']} - {result['name']}")
        
        if 'parallel_account' in result:
            print(f"   ✅ تم إنشاء الحساب الموازي: {result['parallel_account']['account_number']} - {result['parallel_account']['name']}")
        else:
            print("   ⚠️  لم يتم إنشاء حساب موازي")
    else:
        print(f"   ❌ فشل: {response.text}")
    
    print("\n" + "-" * 70)
    
    # 2. إضافة حساب وزني
    print("\n2️⃣ إضافة حساب وزني جديد...")
    memo_account = {
        "account_number": "7160",
        "name": "بنك البلاد وزني",
        "type": "Asset",
        "transaction_type": "gold",
        "parent_id": None,
        "tracks_weight": True
    }
    
    response = requests.post(f"{base_url}/accounts", json=memo_account)
    print(f"   Status: {response.status_code}")
    
    if response.status_code == 201:
        result = response.json()
        print(f"   ✅ تم إنشاء الحساب: {result['account_number']} - {result['name']}")
        
        if 'parallel_account' in result:
            print(f"   ✅ تم إنشاء الحساب الموازي: {result['parallel_account']['account_number']} - {result['parallel_account']['name']}")
        else:
            print("   ⚠️  لم يتم إنشاء حساب موازي")
    else:
        print(f"   ❌ فشل: {response.text}")

def test_direct():
    """اختبار مباشر عبر الكود"""
    print("\n" + "=" * 70)
    print("🧪 اختبار إنشاء الحسابات الموازية مباشرة")
    print("=" * 70)
    
    with app.app_context():
        # 1. إنشاء حساب مالي
        print("\n1️⃣ إنشاء حساب مالي...")
        financial = Account(
            account_number="1170",
            name="بنك ساب",
            type="Asset",
            transaction_type="cash",
            tracks_weight=False
        )
        db.session.add(financial)
        db.session.flush()
        
        print(f"   ✅ تم إنشاء: {financial.account_number} - {financial.name}")
        
        # إنشاء الحساب الموازي
        parallel = financial.create_parallel_account()
        if parallel:
            print(f"   ✅ الحساب الموازي: {parallel.account_number} - {parallel.name}")
            print(f"   🔗 memo_account_id: {financial.memo_account_id}")
        
        db.session.commit()
        
        # 2. إنشاء حساب وزني
        print("\n2️⃣ إنشاء حساب وزني...")
        memo = Account(
            account_number="7180",
            name="بنك الأول وزني",
            type="Asset",
            transaction_type="gold",
            tracks_weight=True
        )
        db.session.add(memo)
        db.session.flush()
        
        print(f"   ✅ تم إنشاء: {memo.account_number} - {memo.name}")
        
        # إنشاء الحساب الموازي
        parallel = memo.create_parallel_account()
        if parallel:
            print(f"   ✅ الحساب الموازي: {parallel.account_number} - {parallel.name}")
        
        db.session.commit()
        
        # 3. التحقق من الربط
        print("\n3️⃣ التحقق من الربط...")
        financial_check = Account.query.filter_by(account_number="1170").first()
        if financial_check and financial_check.memo_account_id:
            memo_check = Account.query.get(financial_check.memo_account_id)
            print(f"   ✅ الحساب المالي {financial_check.account_number} مربوط بـ {memo_check.account_number}")
        
        print("\n" + "=" * 70)
        print("📊 ملخص الحسابات المنشأة:")
        print("=" * 70)
        
        all_accounts = Account.query.filter(
            Account.account_number.in_(['1150', '71150', '1160', '7160', '1170', '7170', '180', '7180'])
        ).all()
        
        for acc in all_accounts:
            memo_info = ""
            if acc.memo_account_id:
                memo_acc = Account.query.get(acc.memo_account_id)
                memo_info = f" 🔗 {memo_acc.account_number}"
            
            print(f"   {acc.account_number:6} | {acc.name:30} | {acc.transaction_type:4} {memo_info}")

if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == 'api':
        # اختبار عبر API (يتطلب تشغيل السيرفر)
        test_via_api()
    else:
        # اختبار مباشر
        test_direct()
    
    print("\n✅ انتهى الاختبار")
