#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""اختبار (يدوي) لتطبيق القاعدة الذهبية في الفواتير.

ملاحظة: هذا ملف تشغيل يدوي وليس اختبار pytest.
تم وضع كل المنطق تحت `main()` حتى لا يتم تنفيذ أي كود أثناء `pytest` collection.
"""


def main() -> int:
    from datetime import datetime

    from app import app, db
    from models import Account, Customer, Item, JournalEntry, JournalEntryLine
    from dual_system_helpers import create_dual_journal_entry

    print("=" * 80)
    print("🧪 اختبار القاعدة الذهبية في الفواتير")
    print("=" * 80)

    with app.app_context():
        customer = Customer.query.first()
        item = Item.query.first()

        if not customer or not item:
            print("❌ لا توجد بيانات أساسية (عميل أو صنف)")
            return 1

        print("\n📋 البيانات:")
        print(f"   العميل: {customer.name}")
        print(f"   الصنف: {item.name} - عيار {item.karat} - وزن {item.weight}جم - سعر {item.price} ريال")

        print("\n🔬 اختبار 1: إنشاء قيد يدوي بسيط")
        print("-" * 80)

        entry = JournalEntry(description="قيد اختبار القاعدة الذهبية", date=datetime.now())
        db.session.add(entry)
        db.session.flush()
        print(f"✅ قيد #{entry.id} تم إنشاؤه")

        cash_acc = Account.query.filter_by(account_number='1100').first()
        revenue_acc = Account.query.filter_by(account_number='40').first()

        if not cash_acc or not revenue_acc:
            print("❌ لم يتم العثور على حسابات 1100 أو 40")
            db.session.rollback()
            return 1

        print("\n📝 إنشاء سطور القيد:")
        print("   1. مدين الصندوق (1100): 1000 ريال")
        print(f"      - memo_account_id: {cash_acc.memo_account_id}")

        create_dual_journal_entry(
            journal_entry_id=entry.id,
            account_id=cash_acc.id,
            cash_debit=1000,
            apply_golden_rule=True,
        )

        print("\n   2. دائن إيرادات بيع الذهب (40): 1000 ريال")
        print(f"      - memo_account_id: {revenue_acc.memo_account_id}")

        create_dual_journal_entry(
            journal_entry_id=entry.id,
            account_id=revenue_acc.id,
            cash_credit=1000,
            apply_golden_rule=True,
        )

        print("\n🔍 فحص التوازن:")
        lines = JournalEntryLine.query.filter_by(journal_entry_id=entry.id).all()

        cash_debit_total = sum(l.debit for l in lines if l.transaction_type == 'cash')
        cash_credit_total = sum(l.credit for l in lines if l.transaction_type == 'cash')
        weight_21k_debit_total = sum(l.weight_21k_debit for l in lines if l.transaction_type == 'gold')
        weight_21k_credit_total = sum(l.weight_21k_credit for l in lines if l.transaction_type == 'gold')

        print("   النقد:")
        print(f"      مدين: {cash_debit_total:.2f} ريال")
        print(f"      دائن: {cash_credit_total:.2f} ريال")
        print(f"      الفرق: {cash_debit_total - cash_credit_total:.2f} ريال")

        print("   الوزن (عيار 21):")
        print(f"      مدين: {weight_21k_debit_total:.3f} جرام")
        print(f"      دائن: {weight_21k_credit_total:.3f} جرام")
        print(f"      الفرق: {weight_21k_debit_total - weight_21k_credit_total:.3f} جرام")

        if abs(cash_debit_total - cash_credit_total) < 0.01 and abs(weight_21k_debit_total - weight_21k_credit_total) < 0.001:
            print("\n✅ القيد متوازن!")
        else:
            print("\n❌ القيد غير متوازن!")

        print("\n📊 تفاصيل السطور:")
        for line in lines:
            acc = line.account
            if line.transaction_type == 'cash':
                print(f"   💰 [{line.transaction_type}] {acc.account_number} - {acc.name}")
                print(f"      مدين: {line.debit:.2f} | دائن: {line.credit:.2f}")
            else:
                print(f"   ⚖️  [{line.transaction_type}] {acc.account_number} - {acc.name}")
                print(f"      وزن 21k: {line.weight_21k_debit:.3f} / {line.weight_21k_credit:.3f}")

        db.session.rollback()
        print("\n🔙 تم التراجع عن التغييرات")

    print("\n" + "=" * 80)
    print("✅ انتهى الاختبار")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
