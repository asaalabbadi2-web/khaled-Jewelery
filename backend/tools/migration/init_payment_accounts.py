"""تهيئة شجرة الحسابات، الخزائن، وأنواع/وسائل الدفع المتوافقة مع النظام الحالي."""

from __future__ import annotations

import os
import sys
from typing import Dict, List, Tuple

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import app, db
from models import (
    Account,
    PaymentMethod,
    PaymentType,
    SafeBox,
    PAYMENT_METHOD_ALLOWED_INVOICE_TYPES,
)


ACCOUNT_DEFINITIONS: List[Dict[str, str]] = [
    {'account_number': '1', 'name': 'الأصول', 'type': 'Asset', 'transaction_type': 'cash'},
    {'account_number': '11', 'name': 'الأصول المتداولة', 'type': 'Asset', 'transaction_type': 'cash', 'parent_number': '1'},
    {'account_number': '110', 'name': 'النقدية والبنوك', 'type': 'Asset', 'transaction_type': 'cash', 'parent_number': '11'},
    {'account_number': '1100', 'name': 'الصندوق النقدي', 'type': 'Asset', 'transaction_type': 'cash', 'account_type': 'cash', 'parent_number': '110'},
    {'account_number': '1110', 'name': 'بنك الأهلي', 'type': 'Asset', 'transaction_type': 'cash', 'account_type': 'bank_account', 'parent_number': '110'},
    {'account_number': '1120', 'name': 'بنك الراجحي', 'type': 'Asset', 'transaction_type': 'cash', 'account_type': 'bank_account', 'parent_number': '110'},
    {'account_number': '1136', 'name': 'بنك الرياض', 'type': 'Asset', 'transaction_type': 'cash', 'account_type': 'bank_account', 'parent_number': '110'},
    {'account_number': '1130', 'name': 'أجهزة نقاط البيع', 'type': 'Asset', 'transaction_type': 'cash', 'parent_number': '110'},
    {'account_number': '1131', 'name': 'مدى - نقاط بيع', 'type': 'Asset', 'transaction_type': 'cash', 'account_type': 'bank_account', 'parent_number': '1130'},
    {'account_number': '1132', 'name': 'فيزا - نقاط بيع', 'type': 'Asset', 'transaction_type': 'cash', 'account_type': 'bank_account', 'parent_number': '1130'},
    {'account_number': '1133', 'name': 'ماستركارد - نقاط بيع', 'type': 'Asset', 'transaction_type': 'cash', 'account_type': 'bank_account', 'parent_number': '1130'},
    {'account_number': '1134', 'name': 'STC Pay - محفظة رقمية', 'type': 'Asset', 'transaction_type': 'cash', 'account_type': 'digital_wallet', 'parent_number': '1130'},
    {'account_number': '1135', 'name': 'Apple Pay - محفظة رقمية', 'type': 'Asset', 'transaction_type': 'cash', 'account_type': 'digital_wallet', 'parent_number': '1130'},
    {'account_number': '1140', 'name': 'تحويلات بنكية مباشرة', 'type': 'Asset', 'transaction_type': 'cash', 'account_type': 'bank_account', 'parent_number': '110'},
    {'account_number': '120', 'name': 'العملاء', 'type': 'Asset', 'transaction_type': 'cash', 'parent_number': '11'},
    {'account_number': '1200', 'name': 'عملاء بيع ذهب', 'type': 'Asset', 'transaction_type': 'cash', 'parent_number': '120'},
    {'account_number': '1201', 'name': 'تابي - مستحق التحصيل', 'type': 'Asset', 'transaction_type': 'cash', 'account_type': 'bnpl', 'parent_number': '120'},
    {'account_number': '1202', 'name': 'تمارا - مستحق التحصيل', 'type': 'Asset', 'transaction_type': 'cash', 'account_type': 'bnpl', 'parent_number': '120'},
]

SAFE_BOX_DEFINITIONS: List[Dict[str, str]] = [
    {
        'code': 'cash_main',
        'name': 'صندوق النقدية الرئيسي',
        'name_en': 'Main Cash Safe',
        'safe_type': 'cash',
        'account_number': '1100',
        'is_default': True,
        'notes': 'الخزينة الرئيسية لاستلام المدفوعات النقدية.',
    },
    {
        'code': 'mada_pos',
        'name': 'جهاز نقاط البيع - مدى',
        'name_en': 'Mada POS',
        'safe_type': 'bank',
        'account_number': '1131',
        'bank_name': 'Mada',
    },
    {
        'code': 'visa_pos',
        'name': 'جهاز نقاط البيع - فيزا',
        'name_en': 'Visa POS',
        'safe_type': 'bank',
        'account_number': '1132',
        'bank_name': 'Visa',
    },
    {
        'code': 'mastercard_pos',
        'name': 'جهاز نقاط البيع - ماستركارد',
        'name_en': 'Mastercard POS',
        'safe_type': 'bank',
        'account_number': '1133',
        'bank_name': 'Mastercard',
    },
    {
        'code': 'stc_pay_wallet',
        'name': 'محفظة STC Pay',
        'name_en': 'STC Pay Wallet',
        'safe_type': 'bank',
        'account_number': '1134',
        'bank_name': 'STC Pay',
    },
    {
        'code': 'apple_pay_wallet',
        'name': 'محفظة Apple Pay',
        'name_en': 'Apple Pay Wallet',
        'safe_type': 'bank',
        'account_number': '1135',
        'bank_name': 'Apple Pay',
    },
    {
        'code': 'bank_transfer',
        'name': 'تحويل بنكي مباشر',
        'name_en': 'Direct Bank Transfer',
        'safe_type': 'bank',
        'account_number': '1140',
        'bank_name': 'Bank Transfer',
    },
    {
        'code': 'tabby_wallet',
        'name': 'تابي - مستحق تحصيل',
        'name_en': 'Tabby Receivable',
        'safe_type': 'bank',
        'account_number': '1201',
        'bank_name': 'Tabby',
    },
    {
        'code': 'tamara_wallet',
        'name': 'تمارا - مستحق تحصيل',
        'name_en': 'Tamara Receivable',
        'safe_type': 'bank',
        'account_number': '1202',
        'bank_name': 'Tamara',
    },
]

PAYMENT_TYPE_DEFINITIONS: List[Dict[str, str]] = [
    {'code': 'cash', 'name_ar': 'نقداً', 'name_en': 'Cash', 'icon': '💵', 'category': 'cash', 'sort_order': 1},
    {'code': 'mada', 'name_ar': 'بطاقة مدى', 'name_en': 'Mada', 'icon': '💳', 'category': 'card', 'sort_order': 2},
    {'code': 'visa', 'name_ar': 'بطاقة فيزا', 'name_en': 'Visa', 'icon': '💳', 'category': 'card', 'sort_order': 3},
    {'code': 'mastercard', 'name_ar': 'بطاقة ماستركارد', 'name_en': 'Mastercard', 'icon': '💳', 'category': 'card', 'sort_order': 4},
    {'code': 'stc_pay', 'name_ar': 'STC Pay', 'name_en': 'STC Pay', 'icon': '📱', 'category': 'digital_wallet', 'sort_order': 5},
    {'code': 'apple_pay', 'name_ar': 'Apple Pay', 'name_en': 'Apple Pay', 'icon': '📱', 'category': 'digital_wallet', 'sort_order': 6},
    {'code': 'tabby', 'name_ar': 'تابي', 'name_en': 'Tabby', 'icon': '🛍️', 'category': 'bnpl', 'sort_order': 7},
    {'code': 'tamara', 'name_ar': 'تمارا', 'name_en': 'Tamara', 'icon': '🛍️', 'category': 'bnpl', 'sort_order': 8},
    {'code': 'bank_transfer', 'name_ar': 'تحويل بنكي', 'name_en': 'Bank Transfer', 'icon': '🏦', 'category': 'bank_transfer', 'sort_order': 9},
]

DEFAULT_INVOICE_TYPES = list(PAYMENT_METHOD_ALLOWED_INVOICE_TYPES)

PAYMENT_METHOD_DEFINITIONS: List[Dict[str, object]] = [
    {
        'payment_type': 'cash',
        'name': 'نقداً',
        'safe_box_code': 'cash_main',
        'commission_rate': 0.0,
        'settlement_days': 0,
        'display_order': 1,
    },
    {
        'payment_type': 'mada',
        'name': 'بطاقة مدى',
        'safe_box_code': 'mada_pos',
        'commission_rate': 1.5,
        'settlement_days': 2,
        'display_order': 2,
    },
    {
        'payment_type': 'visa',
        'name': 'بطاقة فيزا',
        'safe_box_code': 'visa_pos',
        'commission_rate': 2.5,
        'settlement_days': 3,
        'display_order': 3,
    },
    {
        'payment_type': 'mastercard',
        'name': 'بطاقة ماستركارد',
        'safe_box_code': 'mastercard_pos',
        'commission_rate': 2.5,
        'settlement_days': 3,
        'display_order': 4,
    },
    {
        'payment_type': 'stc_pay',
        'name': 'STC Pay',
        'safe_box_code': 'stc_pay_wallet',
        'commission_rate': 1.5,
        'settlement_days': 1,
        'display_order': 5,
    },
    {
        'payment_type': 'apple_pay',
        'name': 'Apple Pay',
        'safe_box_code': 'apple_pay_wallet',
        'commission_rate': 2.0,
        'settlement_days': 2,
        'display_order': 6,
    },
    {
        'payment_type': 'bank_transfer',
        'name': 'تحويل بنكي',
        'safe_box_code': 'bank_transfer',
        'commission_rate': 0.0,
        'settlement_days': 1,
        'display_order': 7,
    },
    {
        'payment_type': 'tabby',
        'name': 'تابي (BNPL)',
        'safe_box_code': 'tabby_wallet',
        'commission_rate': 4.0,
        'settlement_days': 7,
        'display_order': 8,
    },
    {
        'payment_type': 'tamara',
        'name': 'تمارا (BNPL)',
        'safe_box_code': 'tamara_wallet',
        'commission_rate': 4.0,
        'settlement_days': 7,
        'display_order': 9,
    },
]


def ensure_account(account_data: Dict[str, str], cache: Dict[str, Account]) -> Tuple[Account, bool, bool]:
    account = Account.query.filter_by(account_number=account_data['account_number']).first()
    created = False
    updated = False

    if not account:
        account = Account(account_number=account_data['account_number'])
        db.session.add(account)
        created = True

    fields = {
        'name': account_data['name'],
        'type': account_data['type'],
        'transaction_type': account_data['transaction_type'],
        'account_type': account_data.get('account_type'),
    }

    for attr, value in fields.items():
        if value is not None and getattr(account, attr) != value:
            setattr(account, attr, value)
            updated = True

    parent_number = account_data.get('parent_number')
    if parent_number:
        parent = cache.get(parent_number) or Account.query.filter_by(account_number=parent_number).first()
        if parent and account.parent_id != parent.id:
            account.parent_id = parent.id
            updated = True

    cache[account.account_number] = account
    return account, created, updated


def init_chart_of_accounts() -> Dict[str, Account]:
    print("🏦 إنشاء/تحديث شجرة الحسابات...")
    cache: Dict[str, Account] = {}
    created = 0
    updated = 0

    for acc in ACCOUNT_DEFINITIONS:
        _, was_created, was_updated = ensure_account(acc, cache)
        created += 1 if was_created else 0
        updated += 1 if was_updated and not was_created else 0

    db.session.commit()
    print(f"   ✅ حسابات جديدة: {created} | محدّثة: {updated}")
    return cache


def ensure_safe_box(safe_box_data: Dict[str, str], accounts_cache: Dict[str, Account]) -> Tuple[SafeBox, bool, bool]:
    account = accounts_cache.get(safe_box_data['account_number']) or Account.query.filter_by(account_number=safe_box_data['account_number']).first()
    if not account:
        raise RuntimeError(f"الحساب {safe_box_data['account_number']} غير موجود ولا يمكن إنشاء الخزينة {safe_box_data['name']}.")

    safe_box = SafeBox.query.filter_by(name=safe_box_data['name']).first()
    created = False
    updated = False

    if not safe_box:
        safe_box = SafeBox(
            name=safe_box_data['name'],
            name_en=safe_box_data.get('name_en'),
            safe_type=safe_box_data.get('safe_type', 'cash'),
            account_id=account.id,
            bank_name=safe_box_data.get('bank_name'),
            iban=safe_box_data.get('iban'),
            swift_code=safe_box_data.get('swift_code'),
            branch=safe_box_data.get('branch'),
            is_active=True,
            is_default=safe_box_data.get('is_default', False),
            notes=safe_box_data.get('notes'),
        )
        db.session.add(safe_box)
        created = True
    else:
        field_map = {
            'name_en': safe_box_data.get('name_en'),
            'safe_type': safe_box_data.get('safe_type', safe_box.safe_type or 'cash'),
            'account_id': account.id,
            'bank_name': safe_box_data.get('bank_name'),
            'iban': safe_box_data.get('iban'),
            'swift_code': safe_box_data.get('swift_code'),
            'branch': safe_box_data.get('branch'),
            'notes': safe_box_data.get('notes'),
        }

        for attr, value in field_map.items():
            if value is not None and getattr(safe_box, attr) != value:
                setattr(safe_box, attr, value)
                updated = True

    is_default = safe_box_data.get('is_default', False)
    if safe_box.is_default != is_default:
        safe_box.is_default = is_default
        updated = True
        if is_default:
            SafeBox.query.filter(
                SafeBox.safe_type == safe_box.safe_type,
                SafeBox.id != safe_box.id,
                SafeBox.is_default.is_(True)
            ).update({'is_default': False})

    if safe_box.account_id != account.id:
        safe_box.account_id = account.id
        updated = True

    return safe_box, created, updated


def init_safe_boxes(accounts_cache: Dict[str, Account]) -> Dict[str, SafeBox]:
    print("💼 إعداد الخزائن (Safe Boxes)...")
    cache: Dict[str, SafeBox] = {}
    created = 0
    updated = 0

    for sb in SAFE_BOX_DEFINITIONS:
        safe_box, was_created, was_updated = ensure_safe_box(sb, accounts_cache)
        cache[sb['code']] = safe_box
        created += 1 if was_created else 0
        updated += 1 if was_updated and not was_created else 0

    db.session.commit()
    print(f"   ✅ خزائن جديدة: {created} | محدّثة: {updated}")
    return cache


def init_payment_types() -> None:
    print("🧾 تحديث أنواع وسائل الدفع...")
    created = 0
    updated = 0

    for payment_type in PAYMENT_TYPE_DEFINITIONS:
        record = PaymentType.query.filter_by(code=payment_type['code']).first()
        if not record:
            record = PaymentType(code=payment_type['code'])
            db.session.add(record)
            created += 1
        else:
            updated += 1

        record.name_ar = payment_type['name_ar']
        record.name_en = payment_type.get('name_en')
        record.icon = payment_type.get('icon')
        record.category = payment_type.get('category')
        record.is_active = True
        record.sort_order = payment_type.get('sort_order', 0)

    db.session.commit()
    print(f"   ✅ أنواع جديدة: {created} | محدّثة: {updated}")


def init_payment_methods(safe_box_cache: Dict[str, SafeBox]) -> None:
    print("💳 إنشاء/تحديث وسائل الدفع...")
    created = 0
    updated = 0

    for definition in PAYMENT_METHOD_DEFINITIONS:
        safe_box = safe_box_cache.get(definition['safe_box_code'])
        if not safe_box:
            raise RuntimeError(f"لم يتم العثور على الخزينة {definition['safe_box_code']} الخاصة بوسيلة الدفع {definition['name']}")

        payment_method = PaymentMethod.query.filter_by(payment_type=definition['payment_type']).first()
        if not payment_method:
            payment_method = PaymentMethod(payment_type=definition['payment_type'], name=definition['name'])
            db.session.add(payment_method)
            created += 1
        else:
            updated += 1
            payment_method.name = definition['name']

        payment_method.commission_rate = definition['commission_rate']
        payment_method.settlement_days = definition['settlement_days']
        payment_method.display_order = definition.get('display_order', payment_method.display_order or 999)
        payment_method.is_active = definition.get('is_active', True)
        payment_method.default_safe_box_id = safe_box.id
        payment_method.applicable_invoice_types = definition.get('applicable_invoice_types', DEFAULT_INVOICE_TYPES)

    db.session.commit()
    print(f"   ✅ وسائل جديدة: {created} | محدّثة: {updated}")


def main() -> None:
    with app.app_context():
        db.create_all()

        print("\n" + "=" * 70)
        print("🚀 بدء تهيئة الحسابات والخزائن ووسائل الدفع")
        print("=" * 70)

        accounts_cache = init_chart_of_accounts()
        safe_box_cache = init_safe_boxes(accounts_cache)
        init_payment_types()
        init_payment_methods(safe_box_cache)

        print("=" * 70)
        print(f"📊 إجمالي الحسابات: {Account.query.count()}")
        print(f"💼 إجمالي الخزائن: {SafeBox.query.count()}")
        print(f"💳 إجمالي وسائل الدفع: {PaymentMethod.query.count()}")
        print(f"🧾 أنواع وسائل الدفع: {PaymentType.query.count()}")
        print("=" * 70 + "\n")


if __name__ == '__main__':
    main()
