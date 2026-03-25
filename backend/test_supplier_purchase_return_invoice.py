from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from app import app, db
from models import InvoiceItem, InvoicePayment, PaymentMethod, Supplier, Account, JournalEntry


def _ensure_receivable_payment_method() -> int:
    pm = PaymentMethod.query.filter_by(payment_type='receivable').first()
    if pm:
        return int(pm.id)
    pm = PaymentMethod(payment_type='receivable', name='آجل - اختبار', commission_rate=0.0, is_active=True)
    db.session.add(pm)
    db.session.flush()
    return int(pm.id)


def _get_supplier_financial_account_id(supplier_id: int) -> int:
    supplier = Supplier.query.get(supplier_id)
    assert supplier is not None
    assert supplier.account_id is not None
    acc = Account.query.get(int(supplier.account_id))
    assert acc is not None
    return int(acc.id)


def test_supplier_purchase_return_within_limits_creates_no_payment_when_amount_paid_zero(auth_headers):
    with app.app_context():
        # Ensure a supplier exists (id=1 is seeded), and a receivable payment method.
        supplier = Supplier.query.get(1)
        if not supplier:
            supplier = Supplier(id=1, supplier_code=f"S-TST-{uuid.uuid4().hex[:6]}", name='مورد اختبار')
            db.session.add(supplier)
            db.session.commit()

        receivable_pm_id = _ensure_receivable_payment_method()
        db.session.commit()

    # 1) Create original supplier purchase invoice with one item (qty=2, weight per unit=10)
    original_payload = {
        'invoice_type': 'شراء',
        'supplier_id': 1,
        'gold_type': 'new',
        'date': datetime.utcnow().date().isoformat(),
        'total': 0,
        'items': [
            {
                'name': 'قطعة اختبار شراء',
                'karat': 21,
                'weight': 10.0,
                'quantity': 2,
                'price': 0,
            }
        ],
    }

    with app.test_client() as client:
        resp = client.post('/api/invoices', json=original_payload, headers=auth_headers)

    assert resp.status_code in (200, 201), resp.get_data(as_text=True)
    original_invoice = resp.get_json()
    original_invoice_id = int(original_invoice['id'])

    with app.app_context():
        orig_item = InvoiceItem.query.filter_by(invoice_id=original_invoice_id).first()
        assert orig_item is not None
        original_invoice_item_id = int(orig_item.id)

    # 2) Create supplier purchase return within limits: qty=1, weight=10
    return_payload = {
        'invoice_type': 'مرتجع شراء (مورد)',
        'supplier_id': 1,
        'gold_type': 'new',
        'date': datetime.utcnow().date().isoformat(),
        'original_invoice_id': original_invoice_id,
        'payment_method_id': receivable_pm_id,
        'amount_paid': 0,
        'items': [
            {
                'name': 'قطعة اختبار مرتجع',
                'karat': 21,
                'weight': 10.0,
                'quantity': 1,
                'price': 0,
                'original_invoice_item_id': original_invoice_item_id,
            }
        ],
    }

    with app.test_client() as client:
        resp2 = client.post('/api/invoices', json=return_payload, headers=auth_headers)

    assert resp2.status_code in (200, 201), resp2.get_data(as_text=True)
    return_invoice = resp2.get_json()
    return_invoice_id = int(return_invoice['id'])
    with app.app_context():
        je = JournalEntry.query.filter_by(reference_type='invoice', reference_id=return_invoice_id).first()
        assert je is not None
        return_je_id = int(je.id)
    assert return_je_id > 0

    with app.app_context():
        # amount_paid=0 (explicit) must not create an InvoicePayment row.
        payments = InvoicePayment.query.filter_by(invoice_id=return_invoice_id).all()
        assert payments == []

        # Ensure supplier line posts to supplier's financial account (not cash fallback).
        supplier_fin_acc_id = _get_supplier_financial_account_id(1)

        from models import JournalEntryLine

        supplier_lines = JournalEntryLine.query.filter_by(
            journal_entry_id=return_je_id,
            supplier_id=1,
        ).all()
        assert supplier_lines, 'Expected supplier-tagged JE line(s)'
        assert any(int(ln.account_id) == supplier_fin_acc_id for ln in supplier_lines)


def test_supplier_purchase_return_rejects_exceeding_quantity(auth_headers):
    # Create original invoice qty=1
    original_payload = {
        'invoice_type': 'شراء',
        'supplier_id': 1,
        'gold_type': 'new',
        'date': datetime.utcnow().date().isoformat(),
        'total': 0,
        'items': [
            {
                'name': 'قطعة اختبار شراء 2',
                'karat': 21,
                'weight': 5.0,
                'quantity': 1,
                'price': 0,
            }
        ],
    }

    with app.test_client() as client:
        resp = client.post('/api/invoices', json=original_payload, headers=auth_headers)

    assert resp.status_code in (200, 201), resp.get_data(as_text=True)
    original_invoice_id = int(resp.get_json()['id'])

    with app.app_context():
        orig_item = InvoiceItem.query.filter_by(invoice_id=original_invoice_id).first()
        assert orig_item is not None
        original_invoice_item_id = int(orig_item.id)

    # Return qty=2 > original qty=1 should be rejected.
    return_payload = {
        'invoice_type': 'مرتجع شراء (مورد)',
        'supplier_id': 1,
        'gold_type': 'new',
        'date': datetime.utcnow().date().isoformat(),
        'original_invoice_id': original_invoice_id,
        'items': [
            {
                'name': 'قطعة اختبار مرتجع 2',
                'karat': 21,
                'weight': 5.0,
                'quantity': 2,
                'price': 0,
                'original_invoice_item_id': original_invoice_item_id,
            }
        ],
    }

    with app.test_client() as client:
        resp2 = client.post('/api/invoices', json=return_payload, headers=auth_headers)

    assert resp2.status_code == 400
    body = resp2.get_json() or {}
    assert body.get('error') in {
        'return_quantity_exceeds_original',
        'return_weight_exceeds_original',
        'original_invoice_item_not_found',
        'missing_original_invoice_item_id',
    }, body


def test_supplier_purchase_return_allows_legacy_without_original_invoice(auth_headers):
    """Old/legacy supplier returns may not have a selectable original invoice."""
    payload = {
        'invoice_type': 'مرتجع شراء (مورد)',
        'supplier_id': 1,
        'gold_type': 'new',
        'date': datetime.utcnow().date().isoformat(),
        'total': 0,
        'amount_paid': 0,
        'karat_lines': [
            {
                'karat': 21,
                'weight_grams': 1.0,
                'wage_per_gram': 0.0,
                'description': 'legacy return without original invoice',
            }
        ],
        'items': [],
    }

    with app.test_client() as client:
        resp = client.post('/api/invoices', json=payload, headers=auth_headers)

    assert resp.status_code in (200, 201), resp.get_data(as_text=True)
