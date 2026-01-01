#!/usr/bin/env python3
"""
اختبار القاعدة الذهبية في القيود اليدوية
========================================

يختبر تطبيق القاعدة الذهبية على القيود اليدوية:
- قيد بدون القاعدة (يدوي بالكامل)
- قيد مع القاعدة (تحويل تلقائي من نقد إلى وزن)
"""

import requests
import json
from datetime import datetime

BASE_URL = "http://127.0.0.1:8001/api"

def test_manual_entry_without_golden_rule():
    """اختبار قيد يدوي بدون القاعدة الذهبية"""
    print("\n" + "=" * 70)
    print("🧪 اختبار 1: قيد يدوي بدون القاعدة الذهبية")
    print("=" * 70)
    
    payload = {
        "date": datetime.now().isoformat(),
        "description": "قيد يدوي - بدون قاعدة ذهبية",
        "apply_golden_rule": False,
        "lines": [
            {
                "account_id": 1,  # افترض حساب الصندوق
                "cash_debit": 1000.0,
                "cash_credit": 0.0,
                "debit_21k": 0.0,  # يدوي
                "credit_21k": 0.0
            },
            {
                "account_id": 2,  # افترض حساب إيرادات
                "cash_debit": 0.0,
                "cash_credit": 1000.0,
                "debit_21k": 0.0,
                "credit_21k": 0.0  # يدوي
            }
        ]
    }
    
    response = requests.post(f"{BASE_URL}/journal_entries", json=payload)
    print(f"\nStatus: {response.status_code}")
    
    if response.status_code == 201:
        result = response.json()
        print(f"✅ تم إنشاء القيد #{result['id']}")
        print(f"   الوصف: {result['description']}")
        print(f"   عدد الأسطر: {len(result.get('lines', []))}")
    else:
        print(f"❌ فشل: {response.text}")
    
    return response.status_code == 201


def test_manual_entry_with_golden_rule():
    """اختبار قيد يدوي مع القاعدة الذهبية"""
    print("\n" + "=" * 70)
    print("🧪 اختبار 2: قيد يدوي مع القاعدة الذهبية")
    print("=" * 70)
    
    # الحصول على سعر الذهب أولاً
    gold_response = requests.get(f"{BASE_URL}/gold_price")
    if gold_response.status_code != 200:
        print("❌ تعذر الحصول على سعر الذهب")
        return False
    
    gold_data = gold_response.json()
    gold_price = gold_data.get('price_main_karat') or gold_data.get('price_per_gram_main_karat') or gold_data.get('price_24k')
    main_karat = gold_data.get('main_karat', 21)
    
    if not gold_price:
        print("❌ لم يتم العثور على سعر الذهب في الاستجابة")
        return False
    
    print(f"\n💰 سعر الذهب عيار {main_karat}: {gold_price} ريال/جرام")
    
    cash_amount = 1000.0
    expected_weight = cash_amount / gold_price
    print(f"💵 المبلغ النقدي: {cash_amount} ريال")
    print(f"⚖️  الوزن المتوقع: {expected_weight:.3f} جرام")
    
    payload = {
        "date": datetime.now().isoformat(),
        "description": "قيد يدوي - مع القاعدة الذهبية",
        "apply_golden_rule": True,  # 🔥 تفعيل القاعدة
        "lines": [
            {
                "account_id": 1,  # الصندوق
                "cash_debit": cash_amount,
                "cash_credit": 0.0
                # لا حاجة لإدخال القيم الوزنية - ستُحسب تلقائياً
            },
            {
                "account_id": 2,  # الإيرادات
                "cash_debit": 0.0,
                "cash_credit": cash_amount
                # لا حاجة لإدخال القيم الوزنية - ستُحسب تلقائياً
            }
        ]
    }
    
    response = requests.post(f"{BASE_URL}/journal_entries", json=payload)
    print(f"\nStatus: {response.status_code}")
    
    if response.status_code == 201:
        result = response.json()
        print(f"✅ تم إنشاء القيد #{result['id']}")
        print(f"   الوصف: {result['description']}")
        
        # عرض الأسطر مع الأوزان
        if 'lines' in result:
            print("\n   📋 الأسطر:")
            for i, line in enumerate(result['lines'], 1):
                print(f"\n   السطر {i}:")
                print(f"      الحساب: {line.get('account_name', 'N/A')}")
                print(f"      مدين نقدي: {line.get('cash_debit', 0)} ريال")
                print(f"      دائن نقدي: {line.get('cash_credit', 0)} ريال")
                print(f"      مدين وزني (21k): {line.get('debit_21k', 0)} جرام")
                print(f"      دائن وزني (21k): {line.get('credit_21k', 0)} جرام")
        
        return True
    else:
        try:
            error_data = response.json()
            print(f"❌ فشل: {error_data.get('error', 'خطأ غير معروف')}")
        except:
            print(f"❌ فشل: {response.text}")
        return False


def test_mixed_entry():
    """اختبار قيد مختلط (بعض الأسطر بقيم وزنية يدوية)"""
    print("\n" + "=" * 70)
    print("🧪 اختبار 3: قيد مختلط (قاعدة + قيم يدوية)")
    print("=" * 70)
    
    gold_response = requests.get(f"{BASE_URL}/gold_price")
    if gold_response.status_code != 200:
        print("❌ تعذر الحصول على سعر الذهب")
        return False
    
    gold_data = gold_response.json()
    gold_price = gold_data.get('price_main_karat') or gold_data.get('price_per_gram_main_karat') or gold_data.get('price_24k')
    main_karat = gold_data.get('main_karat', 21)
    
    if not gold_price:
        print("❌ لم يتم العثور على سعر الذهب")
        return False
    
    payload = {
        "date": datetime.now().isoformat(),
        "description": "قيد مختلط - قاعدة ذهبية + وزن فعلي (مخزون)",
        "apply_golden_rule": True,
        "lines": [
            {
                "account_id": 1,  # الصندوق
                "cash_debit": 1000.0,
                "cash_credit": 0.0
                # سيُحسب الوزن تلقائياً
            },
            {
                "account_id": 3,  # المخزون (استثناء)
                "cash_debit": 0.0,
                "cash_credit": 0.0,
                "debit_21k": 10.0,  # وزن فعلي (لن يتغير)
                "credit_21k": 0.0
            },
            {
                "account_id": 2,  # حساب آخر
                "cash_debit": 0.0,
                "cash_credit": 1000.0
                # سيُحسب الوزن تلقائياً
            },
            {
                "account_id": 3,  # المخزون
                "cash_debit": 0.0,
                "cash_credit": 0.0,
                "debit_21k": 0.0,
                "credit_21k": 10.0  # وزن فعلي
            }
        ]
    }
    
    response = requests.post(f"{BASE_URL}/journal_entries", json=payload)
    print(f"\nStatus: {response.status_code}")
    
    if response.status_code == 201:
        result = response.json()
        print(f"✅ تم إنشاء القيد #{result['id']}")
        return True
    else:
        print(f"❌ فشل: {response.text}")
        return False


def main():
    """تشغيل جميع الاختبارات"""
    print("\n" + "=" * 70)
    print("🔬 اختبارات القاعدة الذهبية في القيود اليدوية")
    print("=" * 70)
    
    # التحقق من تشغيل السيرفر
    try:
        response = requests.get(f"{BASE_URL}/gold_price")
        if response.status_code != 200:
            print("\n❌ السيرفر لا يعمل أو لا يوجد سعر ذهب")
            print("   قم بتشغيل السيرفر أولاً: cd backend && python app.py")
            return
    except requests.exceptions.ConnectionError:
        print("\n❌ لا يمكن الاتصال بالسيرفر")
        print("   قم بتشغيل السيرفر أولاً: cd backend && python app.py")
        return
    
    results = []
    
    # الاختبار 1
    results.append(("قيد يدوي بدون قاعدة", test_manual_entry_without_golden_rule()))
    
    # الاختبار 2
    results.append(("قيد مع القاعدة الذهبية", test_manual_entry_with_golden_rule()))
    
    # الاختبار 3
    results.append(("قيد مختلط", test_mixed_entry()))
    
    # ملخص النتائج
    print("\n" + "=" * 70)
    print("📊 ملخص النتائج:")
    print("=" * 70)
    
    for test_name, result in results:
        status = "✅ نجح" if result else "❌ فشل"
        print(f"   {status} - {test_name}")
    
    total = len(results)
    passed = sum(1 for _, r in results if r)
    print(f"\nالإجمالي: {passed}/{total} نجح")
    
    print("\n" + "=" * 70)


if __name__ == '__main__':
    main()
