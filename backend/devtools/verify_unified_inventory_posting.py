#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Verify unified inventory posting across invoice types.

Creates a small set of invoices through the real `/api/invoices` endpoint and
asserts that inventory journal lines do not spread across per-karat inventory
accounts (1300/1310/1320/1330) when unified inventory is configured.

Safe to run on a dev database. It will insert test Customer/Supplier/Invoices.
"""

import os
import sys
from datetime import datetime

# Ensure request has a current_user without an Authorization header.
os.environ.setdefault('BYPASS_AUTH_FOR_DEVELOPMENT', '1')

# When executed from backend/devtools, ensure backend/ is importable.
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app import app  # noqa: E402
from models import (
    db,
    Settings,
    Account,
    SafeBox,
    PaymentMethod,
    Customer,
    Supplier,
    JournalEntry,
)


LEGACY_INVENTORY_NUMBERS = ['1300', '1310', '1320', '1330']


def _ensure_settings():
    row = Settings.query.first()
    if not row:
        row = Settings()
        db.session.add(row)
        db.session.flush()

    # Keep invoice creation usable for this test.
    try:
        row.require_auth_for_invoice_create = False
    except Exception:
        pass

    # Prefer unified inventory account as a number if not set.
    try:
        if getattr(row, 'inventory_account_id', None) in (None, '', 0, False):
            row.inventory_account_id = 1310
    except Exception:
        pass

    db.session.add(row)
    db.session.commit()
    return row


def _ensure_cash_payment_method() -> PaymentMethod:
    pm = PaymentMethod.query.filter_by(is_active=True).first()
    if pm and pm.default_safe_box_id:
        return pm

    cash_safe = SafeBox.query.filter_by(safe_type='cash', is_active=True).first()
    if not cash_safe:
        # Create a basic cash safe box linked to cash account 1100 (fallback 110).
        cash_acc = Account.query.filter_by(account_number='1100').first() or Account.query.filter_by(account_number='110').first()
        if not cash_acc:
            raise RuntimeError('Missing cash account 1100/110; cannot create test payment method')

        cash_safe = SafeBox(
            name='خزينة نقدية (اختبار)',
            name_en='Test Cash Safe',
            safe_type='cash',
            account_id=cash_acc.id,
            karat=None,
            is_active=True,
            is_default=False,
            notes='Created by verify_unified_inventory_posting.py',
            created_by='devtools',
        )
        db.session.add(cash_safe)
        db.session.flush()

    if not pm:
        pm = PaymentMethod(
            payment_type='cash',
            name='نقدي (اختبار)',
            commission_rate=0.0,
            settlement_days=0,
            is_active=True,
            display_order=1,
            default_safe_box_id=cash_safe.id,
        )
        db.session.add(pm)
        db.session.flush()
    else:
        pm.default_safe_box_id = cash_safe.id
        db.session.add(pm)

    db.session.commit()
    return pm


def _ensure_customer() -> Customer:
    c = Customer.query.first()
    if c:
        return c
    c = Customer(customer_code='C-TEST-0001', name='عميل اختبار')
    db.session.add(c)
    db.session.commit()
    return c


def _ensure_supplier() -> Supplier:
    s = Supplier.query.first()
    if s:
        return s
    s = Supplier(supplier_code='S-TEST-0001', name='مورد اختبار')
    db.session.add(s)
    db.session.commit()
    return s


def _post_invoice(client, payload: dict) -> dict:
    resp = client.post('/api/invoices', json=payload)
    try:
        body = resp.get_json(force=True)
    except Exception:
        body = {'raw': resp.data.decode('utf-8', errors='ignore')}

    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Invoice create failed ({resp.status_code}): {body}")

    return body


def _inventory_numbers_used_for_invoice(invoice_id: int):
    # Find journal entries linked to this invoice.
    entries = JournalEntry.query.filter_by(reference_type='invoice', reference_id=invoice_id).all()
    if not entries:
        # Fallback: some older code may not set reference_type; try by reference_id only.
        entries = JournalEntry.query.filter_by(reference_id=invoice_id).all()

    used = []
    for je in entries:
        for ln in (je.lines or []):
            if getattr(ln, 'is_deleted', False):
                continue
            acc = Account.query.get(ln.account_id) if getattr(ln, 'account_id', None) else None
            if not acc:
                continue
            if str(acc.account_number) in LEGACY_INVENTORY_NUMBERS:
                used.append(str(acc.account_number))

    return sorted(set(used))


def _assert_expected_inventory(label: str, inv_id: int, expected_number: str):
    used = _inventory_numbers_used_for_invoice(inv_id)
    print(f"[{label}] invoice_id={inv_id} inventory_accounts_used={used} expected={expected_number}")
    if not used:
        raise SystemExit(f"FAILED: no inventory account detected for {label} invoice_id={inv_id}")
    if len(used) != 1 or used[0] != expected_number:
        raise SystemExit(f"FAILED: {label} invoice_id={inv_id} expected {expected_number} but got {used}")


def main():
    with app.app_context():
        _ensure_settings()
        pm = _ensure_cash_payment_method()
        customer = _ensure_customer()
        supplier = _ensure_supplier()

        now = datetime.now().replace(microsecond=0).isoformat()

        client = app.test_client()

        # 1) Sale
        sale = _post_invoice(
            client,
            {
                'invoice_type': 'بيع',
                'gold_type': 'new',
                'customer_id': customer.id,
                'date': now,
                'total': 1000.0,
                'amount_paid': 1000.0,
                'payments': [
                    {'payment_method_id': pm.id, 'amount': 1000.0},
                ],
                'karat_lines': [
                    {'karat': 21, 'weight_grams': 1.5, 'gold_value_cash': 1000.0, 'manufacturing_wage_cash': 0.0},
                ],
            },
        )
        sale_id = int(sale.get('id') or sale.get('invoice', {}).get('id'))

        # 2) Customer scrap purchase
        purchase = _post_invoice(
            client,
            {
                'invoice_type': 'شراء من عميل',
                'gold_type': 'scrap',
                'customer_id': customer.id,
                'date': now,
                'total': 500.0,
                'amount_paid': 500.0,
                'payments': [
                    {'payment_method_id': pm.id, 'amount': 500.0},
                ],
                'karat_lines': [
                    {'karat': 18, 'weight_grams': 2.0, 'gold_value_cash': 500.0, 'manufacturing_wage_cash': 0.0},
                ],
            },
        )
        purchase_id = int(purchase.get('id') or purchase.get('invoice', {}).get('id'))

        # 3) Supplier purchase
        supplier_purchase = _post_invoice(
            client,
            {
                'invoice_type': 'شراء',
                'gold_type': 'new',
                'supplier_id': supplier.id,
                'date': now,
                'total': 2000.0,
                'amount_paid': 2000.0,
                'payments': [
                    {'payment_method_id': pm.id, 'amount': 2000.0},
                ],
                'karat_lines': [
                    {'karat': 21, 'weight_grams': 3.0, 'gold_value_cash': 2000.0, 'manufacturing_wage_cash': 0.0},
                ],
            },
        )
        supplier_purchase_id = int(supplier_purchase.get('id') or supplier_purchase.get('invoice', {}).get('id'))

        # 4) Sale return (must match original customer)
        sale_return = _post_invoice(
            client,
            {
                'invoice_type': 'مرتجع بيع',
                'gold_type': 'new',
                'customer_id': customer.id,
                'original_invoice_id': sale_id,
                'return_reason': 'اختبار توحيد المخزون',
                'date': now,
                'total': 200.0,
                'amount_paid': 200.0,
                'payments': [
                    {'payment_method_id': pm.id, 'amount': 200.0},
                ],
                'karat_lines': [
                    {'karat': 21, 'weight_grams': 0.3, 'gold_value_cash': 200.0, 'manufacturing_wage_cash': 0.0},
                ],
            },
        )
        sale_return_id = int(sale_return.get('id') or sale_return.get('invoice', {}).get('id'))

        _assert_expected_inventory('بيع (معروض للبيع)', sale_id, '1300')
        _assert_expected_inventory('شراء من عميل (كسر)', purchase_id, '1310')
        _assert_expected_inventory('شراء (مورد) (معروض للبيع)', supplier_purchase_id, '1300')
        _assert_expected_inventory('مرتجع بيع (معروض للبيع)', sale_return_id, '1300')

        print('OK: inventory posting matches expected (1300 new / 1310 scrap) and remains unified across karats.')


if __name__ == '__main__':
    main()
