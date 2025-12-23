#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
اختبار تطبيق القاعدة الذهبية في الفواتير
"""

from app import app, db
from models import Invoice, InvoiceItem, Customer, Item, Account, JournalEntry, JournalEntryLine
from dual_system_helpers import create_dual_journal_entry
from datetime import datetime

print("=" * 80)
print("🧪 اختبار القاعدة الذهبية في الفواتير")
print("=" * 80)

with app.app_context():
    # الحصول على البيانات الأساسية
    customer = Customer.query.first()
    item = Item.query.first()
    
    if not customer or not item:
        print("❌ لا توجد بيانات أساسية (عميل أو صنف)")
        exit(1)
    
    print(f"\n📋 البيانات:")
    print(f"   العميل: {customer.name}")
    print(f"   الصنف: {item.name} - عيار {item.karat} - وزن {item.weight}جم - سعر {item.price} ريال")
    
    # إنشاء قيد يدوي لاختبار القاعدة الذهبية
    print(f"\n🔬 اختبار 1: إنشاء قيد يدوي بسيط")
    print("-" * 80)
    
    # إنشاء قيد جديد
    entry = JournalEntry(
        description="قيد اختبار القاعدة الذهبية",
        date=datetime.now()
    )
    db.session.add(entry)
    db.session.flush()
    
    print(f"✅ قيد #{entry.id} تم إنشاؤه")
    
    # الحصول على حساب الصندوق
    cash_acc = Account.query.filter_by(account_number='1100').first()
    revenue_acc = Account.query.filter_by(account_number='40').first()
    
    print(f"\n📝 إنشاء سطور القيد:")
    print(f"   1. مدين الصندوق (1100): 1000 ريال")
    print(f"      - memo_account_id: {cash_acc.memo_account_id}")
    
    # سطر 1: مدين الصندوق
    create_dual_journal_entry(
        journal_entry_id=entry.id,
        account_id=cash_acc.id,
        cash_debit=1000,
        apply_golden_rule=True
    )
    
    print(f"\n   2. دائن إيرادات بيع الذهب (40): 1000 ريال")
    print(f"      - memo_account_id: {revenue_acc.memo_account_id}")
    
    # سطر 2: دائن الإيرادات
    create_dual_journal_entry(
        journal_entry_id=entry.id,
        account_id=revenue_acc.id,
        cash_credit=1000,
        apply_golden_rule=True
    )
    
    # التحقق من التوازن
    print(f"\n🔍 فحص التوازن:")
    lines = JournalEntryLine.query.filter_by(journal_entry_id=entry.id).all()
    
    cash_debit_total = sum(l.debit for l in lines if l.transaction_type == 'cash')
    cash_credit_total = sum(l.credit for l in lines if l.transaction_type == 'cash')
    weight_21k_debit_total = sum(l.weight_21k_debit for l in lines if l.transaction_type == 'gold')
    weight_21k_credit_total = sum(l.weight_21k_credit for l in lines if l.transaction_type == 'gold')
    
    print(f"   النقد:")
    print(f"      مدين: {cash_debit_total:.2f} ريال")
    print(f"      دائن: {cash_credit_total:.2f} ريال")
    print(f"      الفرق: {cash_debit_total - cash_credit_total:.2f} ريال")
    
    print(f"   الوزن (عيار 21):")
    print(f"      مدين: {weight_21k_debit_total:.3f} جرام")
    print(f"      دائن: {weight_21k_credit_total:.3f} جرام")
    print(f"      الفرق: {weight_21k_debit_total - weight_21k_credit_total:.3f} جرام")
    
    if abs(cash_debit_total - cash_credit_total) < 0.01 and abs(weight_21k_debit_total - weight_21k_credit_total) < 0.001:
        print(f"\n✅ القيد متوازن!")
    else:
        print(f"\n❌ القيد غير متوازن!")
    
    print(f"\n📊 تفاصيل السطور:")
    for line in lines:
        acc = line.account
        if line.transaction_type == 'cash':
            print(f"   💰 [{line.transaction_type}] {acc.account_number} - {acc.name}")
            print(f"      مدين: {line.debit:.2f} | دائن: {line.credit:.2f}")
        else:
            print(f"   ⚖️  [{line.transaction_type}] {acc.account_number} - {acc.name}")
            print(f"      وزن 21k: {line.weight_21k_debit:.3f} / {line.weight_21k_credit:.3f}")
    
    # تراجع عن التغييرات
    db.session.rollback()
    print(f"\n🔙 تم التراجع عن التغييرات")

print("\n" + "=" * 80)
print("✅ انتهى الاختبار")
print("=" * 80)
