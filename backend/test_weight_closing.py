#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unit tests for the new weight closing workflow."""

import json
import os
import sys
import unittest
from datetime import datetime

from flask import Flask
from flask import g
from flask import request

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

import recurring_journal_system  # noqa: F401  # Required so metadata includes recurring tables

from models import (
    db,
    Settings,
    Account,
    Invoice,
    InvoiceItem,
    InvoiceKaratLine,
    Office,
    Voucher,
    WeightClosingOrder,
    WeightClosingExecution,
)

from models import JournalEntry, JournalEntryLine
from models import Supplier
from office_supplier_service import ensure_office_supplier
from routes import (
    DEFAULT_WEIGHT_CLOSING_SETTINGS,
    _upsert_weight_closing_order,
    _auto_consume_weight_closing,
    ensure_weight_closing_support_accounts,
    api as api_blueprint,
)


class WeightClosingFlowTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask(__name__)
        cls.app.config['TESTING'] = True
        cls.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
        cls.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(cls.app)
        cls.app.register_blueprint(api_blueprint, url_prefix='/api')

        # Inject an admin user into request context so endpoints protected by
        # @require_permission work in unit tests without the full auth stack.
        @cls.app.before_request
        def _inject_admin_user():
            mode = (request.headers.get('X-Test-Auth') or 'admin').strip().lower()
            if mode in ('none', 'no', '0', 'false', 'unauth'):
                return

            class _TestUser:
                def __init__(self, *, is_admin: bool, username: str, allow_all_permissions: bool):
                    self.is_admin = is_admin
                    self.username = username
                    self._allow_all_permissions = allow_all_permissions

                def has_permission(self, _code: str) -> bool:
                    return bool(self._allow_all_permissions)

            if mode in ('user', 'limited'):
                g.current_user = _TestUser(is_admin=False, username='test-user', allow_all_permissions=False)
            else:
                g.current_user = _TestUser(is_admin=True, username='test-admin', allow_all_permissions=True)

    def _headers(self, auth: str = 'admin'):
        return {'X-Test-Auth': auth}

    def test_auth_none_returns_401(self):
        resp = self.client.get('/api/office-reservations', headers=self._headers('none'))
        self.assertEqual(resp.status_code, 401)

    def test_auth_user_returns_403(self):
        resp = self.client.get('/api/office-reservations', headers=self._headers('user'))
        self.assertEqual(resp.status_code, 403)

    def test_office_reservation_payment_resolves_cash_by_number(self):
        """If settings store 1100 as an account_number (not PK id), posting should still work."""
        # Start from the normal seeded defaults (so weight closing + inventory flow works),
        # but swap the cash account so PK != 1100 while account_number == '1100'.
        seeded_cash = Account.query.get(1100)
        self.assertIsNotNone(seeded_cash)
        db.session.delete(seeded_cash)
        db.session.flush()

        cash_account = Account(
            id=5000,
            account_number='1100',
            name='Main Cash Box',
            type='Asset',
            transaction_type='cash',
            tracks_weight=False,
        )
        db.session.add(cash_account)
        db.session.commit()

        sale_invoice = self._create_sale_invoice(weight_grams=1.5, close_price=240.0)
        _upsert_weight_closing_order(
            sale_invoice,
            close_price_per_gram=240.0,
            settings=DEFAULT_WEIGHT_CLOSING_SETTINGS,
        )
        db.session.commit()

        office = self._create_office(code='OFF-CASH-001', name='Cash Resolve Office')
        payload = {
            'office_id': office.id,
            'reservation_date': datetime.utcnow().isoformat(),
            'karat': 21,
            'weight': 1.5,
            'price_per_gram': 240.0,
            'execution_price_per_gram': 240.0,
            'paid_amount': 360.0,
        }

        resp = self.client.post(
            '/api/office-reservations',
            data=json.dumps(payload),
            content_type='application/json',
            headers=self._headers('admin'),
        )
        self.assertEqual(resp.status_code, 201, resp.get_data(as_text=True))

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self._seed_defaults()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------
    def _seed_defaults(self):
        settings = Settings(
            main_karat=21,
            weight_closing_settings=json.dumps(DEFAULT_WEIGHT_CLOSING_SETTINGS, ensure_ascii=False),
        )
        db.session.add(settings)

        accounts = [
            Account(
                id=15,
                account_number='15',
                name='Cash Box',
                type='Asset',
                transaction_type='cash',
                tracks_weight=False,
            ),
            Account(
                id=24,
                account_number='24',
                name='Inventory 21K',
                type='Asset',
                transaction_type='both',
                tracks_weight=True,
                balance_21k=0.0,
            ),
            Account(
                id=50,
                account_number='50',
                name='Profit & Loss',
                type='Equity',
                transaction_type='cash',
                tracks_weight=False,
            ),
            Account(
                id=55,
                account_number='55',
                name='Sales Gold New',
                type='Revenue',
                transaction_type='cash',
                tracks_weight=False,
            ),
            Account(
                id=83,
                account_number='83',
                name='Cost of Sales',
                type='Expense',
                transaction_type='both',
                tracks_weight=True,
            ),
            Account(
                id=331,
                account_number='331',
                name='Gold Revaluation',
                type='Equity',
                transaction_type='cash',
                tracks_weight=False,
            ),
            Account(
                id=1100,
                account_number='1100',
                name='Main Cash Box',
                type='Asset',
                transaction_type='cash',
                tracks_weight=False,
            ),
            Account(
                id=1290,
                account_number='1290',
                name='جسر مشتريات الكسر والتسكير',
                type='Asset',
                transaction_type='gold',
                tracks_weight=True,
            ),
            Account(
                id=1310,
                account_number='1310',
                name='مخزون ذهب 21',
                type='Asset',
                transaction_type='gold',
                tracks_weight=True,
            ),
        ]
        db.session.add_all(accounts)
        db.session.commit()
        ensure_weight_closing_support_accounts()

    def _create_sale_invoice(self, weight_grams=2.0, karat=21, close_price=250.0):
        next_invoice_type_id = (
            Invoice.query.filter_by(invoice_type='بيع').count() + 1
        )
        invoice = Invoice(
            invoice_type='بيع',
            invoice_type_id=next_invoice_type_id,
            date=datetime.utcnow(),
            total=1000.0,
            gold_subtotal=900.0,
            wage_subtotal=50.0,
            wage_tax_total=5.0,
            total_cost=500.0,
            profit_cash=400.0,
            profit_gold=1.6,
            profit_weight_price_per_gram=close_price,
        )
        db.session.add(invoice)
        db.session.flush()

        item = InvoiceItem(
            invoice_id=invoice.id,
            name='Ring',
            quantity=1,
            price=1000.0,
            net=950.0,
            tax=50.0,
            karat=karat,
            weight=weight_grams,
            wage=50.0,
        )
        db.session.add(item)
        db.session.commit()
        return Invoice.query.get(invoice.id)

    def _create_office(self, code='OFF-000001', name='Main Office'):
        office_account = Account(
            account_number=f'2120-{code.split("-")[-1]}',
            name=f'{name} Ledger',
            type='Liability',
            transaction_type='both',
            tracks_weight=True,
        )
        db.session.add(office_account)
        db.session.flush()

        office = Office(
            office_code=code,
            name=name,
            active=True,
        )
        office.account_category_id = office_account.id
        # compatibility with legacy attribute naming used in routes
        setattr(office, 'account_id', office_account.id)

        db.session.add(office)
        db.session.commit()
        return Office.query.get(office.id)

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------
    def test_upsert_weight_closing_order_calculates_summary(self):
        invoice = self._create_sale_invoice()

        order = _upsert_weight_closing_order(
            invoice,
            close_price_per_gram=250.0,
            settings=DEFAULT_WEIGHT_CLOSING_SETTINGS,
        )
        db.session.commit()

        self.assertIsNotNone(order)
        self.assertAlmostEqual(order.total_weight_main_karat, 2.0)
        self.assertAlmostEqual(order.gold_value_cash, 500.0)
        self.assertEqual(invoice.weight_closing_status, 'open')
        self.assertEqual(invoice.weight_closing_order_number, order.order_number)

    def test_purchase_invoice_consumes_weight_closing_order(self):
        sale_invoice = self._create_sale_invoice(weight_grams=3.0)
        order = _upsert_weight_closing_order(
            sale_invoice,
            close_price_per_gram=220.0,
            settings=DEFAULT_WEIGHT_CLOSING_SETTINGS,
        )
        db.session.commit()
        self.assertIsNotNone(order)

        purchase_invoice = Invoice(
            invoice_type='شراء من عميل',
            invoice_type_id=5,
            date=datetime.utcnow(),
            total=660.0,
            gold_subtotal=660.0,
            wage_subtotal=0.0,
            wage_tax_total=0.0,
        )
        db.session.add(purchase_invoice)
        db.session.flush()

        line = InvoiceKaratLine(
            invoice_id=purchase_invoice.id,
            karat=21,
            weight_grams=3.0,
            gold_value_cash=660.0,
            manufacturing_wage_cash=0.0,
        )
        db.session.add(line)
        db.session.commit()

        result = _auto_consume_weight_closing(purchase_invoice.id)

        refreshed_order = WeightClosingOrder.query.filter_by(invoice_id=sale_invoice.id).first()
        self.assertEqual(result['executions_created'], 1)
        self.assertAlmostEqual(result['weight_consumed'], 3.0)
        self.assertAlmostEqual(refreshed_order.executed_weight_main_karat, 3.0)
        self.assertEqual(refreshed_order.status, 'closed')

        execution = WeightClosingExecution.query.filter_by(order_id=refreshed_order.id).one()
        self.assertEqual(execution.source_invoice_id, purchase_invoice.id)
        self.assertAlmostEqual(execution.weight_main_karat, 3.0)

    def test_office_reservation_consumes_weight_closing_order(self):
        sale_invoice = self._create_sale_invoice(weight_grams=2.5, close_price=230.0)
        order = _upsert_weight_closing_order(
            sale_invoice,
            close_price_per_gram=230.0,
            settings=DEFAULT_WEIGHT_CLOSING_SETTINGS,
        )
        db.session.commit()
        self.assertIsNotNone(order)

        office = self._create_office()

        payload = {
            'office_id': office.id,
            'reservation_date': datetime.utcnow().isoformat(),
            'karat': 21,
            'weight': 2.5,
            'price_per_gram': 230.0,
            'execution_price_per_gram': 230.0,
            'paid_amount': 575.0,
        }

        response = self.client.post(
            '/api/office-reservations',
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 201, msg=response.data)
        data = json.loads(response.data)
        self.assertEqual(data['payment_status'], 'paid')
        self.assertIn('purchase_invoice_id', data)
        self.assertIsNone(data['purchase_invoice_id'])
        self.assertNotIn('weight_consumption', data)
        self.assertAlmostEqual(data['weight_main_karat'], 2.5)

        refreshed_order = WeightClosingOrder.query.get(order.id)
        self.assertEqual(refreshed_order.status, 'open')
        self.assertAlmostEqual(refreshed_order.executed_weight_main_karat or 0.0, 0.0)

        reservation_id = data['id']
        settle_payload = {
            'settlement_date': datetime.utcnow().isoformat(),
            'execution_price_per_gram': 230.0,
        }
        settle_resp = self.client.post(
            f'/api/office-reservations/{reservation_id}/settle',
            data=json.dumps(settle_payload),
            content_type='application/json',
        )
        self.assertEqual(settle_resp.status_code, 200, msg=settle_resp.data)
        settled = json.loads(settle_resp.data)
        self.assertIsNotNone(settled.get('purchase_invoice_id'))
        self.assertIn('weight_consumption', settled)
        self.assertAlmostEqual(settled['weight_consumption']['weight_consumed'], 2.5)

        refreshed_order = WeightClosingOrder.query.get(order.id)
        self.assertEqual(refreshed_order.status, 'closed')
        self.assertAlmostEqual(refreshed_order.executed_weight_main_karat, 2.5)

        refreshed_office = Office.query.get(office.id)
        self.assertEqual(refreshed_office.total_reservations, 1)
        self.assertAlmostEqual(refreshed_office.total_weight_purchased, data['weight_main_karat'])

    def test_office_reservations_listing_with_pagination(self):
        office = self._create_office()

        for idx, weight in enumerate([1.0, 2.0, 3.0], start=1):
            payload = {
                'office_id': office.id,
                'reservation_date': datetime.utcnow().isoformat(),
                'karat': 21,
                'weight': weight,
                'price_per_gram': 200.0 + (idx * 10),
                'execution_price_per_gram': 200.0 + (idx * 10),
                'paid_amount': weight * (200.0 + (idx * 10)),
            }
            response = self.client.post(
                '/api/office-reservations',
                data=json.dumps(payload),
                content_type='application/json',
            )
            self.assertEqual(response.status_code, 201)

        list_response = self.client.get(
            '/api/office-reservations?page=1&per_page=2&order_by=total_amount&order_direction=asc'
        )
        self.assertEqual(list_response.status_code, 200)
        data = json.loads(list_response.data)
        self.assertIn('pagination', data)
        self.assertEqual(data['pagination']['total'], 3)
        self.assertEqual(len(data['data']), 2)
        totals = [entry['total_amount'] for entry in data['data']]
        self.assertListEqual(sorted(totals), totals)

        second_page = self.client.get(
            '/api/office-reservations?page=2&per_page=2&order_by=total_amount&order_direction=asc'
        )
        self.assertEqual(second_page.status_code, 200)
        data_page_2 = json.loads(second_page.data)
        self.assertEqual(len(data_page_2['data']), 1)
        self.assertEqual(data_page_2['pagination']['page'], 2)

    def test_office_reservation_can_be_cancelled_when_unpaid(self):
        office = self._create_office(code='OFF-CANCEL', name='Cancel Office')

        payload = {
            'office_id': office.id,
            'reservation_date': datetime.utcnow().isoformat(),
            'karat': 21,
            'weight': 1.25,
            'price_per_gram': 250.0,
            'execution_price_per_gram': 250.0,
            'paid_amount': 0.0,
        }

        response = self.client.post(
            '/api/office-reservations',
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 201, msg=response.data)
        data = json.loads(response.data)
        self.assertEqual(data['payment_status'], 'pending')
        self.assertIsNone(data.get('purchase_invoice_id'))

        reservation_id = data['id']
        cancel_resp = self.client.post(
            f'/api/office-reservations/{reservation_id}/cancel',
            data=json.dumps({'cancelled_by': 'test'}),
            content_type='application/json',
        )
        self.assertEqual(cancel_resp.status_code, 200, msg=cancel_resp.data)
        cancelled = json.loads(cancel_resp.data)
        self.assertEqual(cancelled.get('status'), 'cancelled')
        self.assertIsNone(cancelled.get('purchase_invoice_id'))

        # Should not create a gold journal entry on cancellation.
        gold_entry = JournalEntry.query.filter_by(
            reference_type='office_reservation',
            reference_id=reservation_id,
        ).first()
        self.assertIsNone(gold_entry)

    def test_reservation_creates_purchase_invoice_and_journal(self):
        """Booking creates no invoice/gold journal; settlement creates them."""
        sale_invoice = self._create_sale_invoice(weight_grams=1.5, close_price=240.0)
        order = _upsert_weight_closing_order(
            sale_invoice,
            close_price_per_gram=240.0,
            settings=DEFAULT_WEIGHT_CLOSING_SETTINGS,
        )
        db.session.commit()

        office = self._create_office(code='OFF-INV-001', name='Invoice Office')

        payload = {
            'office_id': office.id,
            'reservation_date': datetime.utcnow().isoformat(),
            'karat': 21,
            'weight': 1.5,
            'price_per_gram': 240.0,
            'execution_price_per_gram': 240.0,
            'paid_amount': 360.0,
        }

        response = self.client.post(
            '/api/office-reservations',
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 201, msg=response.data)
        data = json.loads(response.data)

        # booking should not create invoice
        self.assertIn('purchase_invoice_id', data)
        self.assertIsNone(data['purchase_invoice_id'])
        reservation_id = data['id']

        # payment voucher should exist (since paid_amount > 0)
        self.assertIn('payment_voucher_id', data)
        voucher = Voucher.query.get(data['payment_voucher_id'])
        self.assertIsNotNone(voucher)
        self.assertEqual(voucher.reference_type, 'office_reservation')
        self.assertEqual(voucher.reference_id, reservation_id)

        # no gold journal should exist at booking time
        gold_entry = JournalEntry.query.filter_by(reference_type='office_reservation', reference_id=reservation_id).first()
        self.assertIsNone(gold_entry)

        expected_total = round(payload['weight'] * payload['price_per_gram'], 2)

        settle_payload = {
            'settlement_date': datetime.utcnow().isoformat(),
            'execution_price_per_gram': 240.0,
        }
        settle_resp = self.client.post(
            f'/api/office-reservations/{reservation_id}/settle',
            data=json.dumps(settle_payload),
            content_type='application/json',
        )
        self.assertEqual(settle_resp.status_code, 200, msg=settle_resp.data)
        settled = json.loads(settle_resp.data)

        inv = Invoice.query.get(settled['purchase_invoice_id'])
        self.assertIsNotNone(inv)
        self.assertEqual(inv.total, expected_total)

        gold_entry = JournalEntry.query.filter_by(reference_type='office_reservation', reference_id=reservation_id).first()
        self.assertIsNotNone(gold_entry)
        self.assertTrue(gold_entry.is_posted)

        lines = JournalEntryLine.query.filter_by(journal_entry_id=gold_entry.id).all()
        self.assertGreaterEqual(len(lines), 2)

        inventory_account = Account.query.filter_by(account_number='1310').first()
        self.assertIsNotNone(inventory_account)

        inventory_line = next(
            line for line in lines
            if line.account_id == inventory_account.id and (line.cash_debit or 0.0) > 0
        )
        self.assertAlmostEqual(inventory_line.cash_debit or 0.0, expected_total)
        self.assertAlmostEqual(inventory_line.credit_21k or 0.0, payload['weight'])

        office_cash_line = next(
            line for line in lines
            if line.account_id == office.account_category_id and (line.cash_credit or 0.0) > 0
        )
        self.assertAlmostEqual(office_cash_line.cash_credit or 0.0, expected_total)

        office_account = Account.query.get(int(office.account_category_id))
        self.assertIsNotNone(office_account)
        self.assertIsNotNone(getattr(office_account, 'memo_account_id', None))
        office_memo_id = int(getattr(office_account, 'memo_account_id'))

        office_weight_line = next(
            line for line in lines
            if line.account_id == office_memo_id and (line.debit_21k or 0.0) > 0
        )
        self.assertAlmostEqual(office_weight_line.debit_21k or 0.0, payload['weight'])

    def test_reservation_partial_payment_creates_partial_invoice(self):
        """Partial payment creates a payment voucher at booking, and a partially_paid invoice on settlement."""
        sale_invoice = self._create_sale_invoice(weight_grams=2.0, close_price=210.0)
        order = _upsert_weight_closing_order(
            sale_invoice,
            close_price_per_gram=210.0,
            settings=DEFAULT_WEIGHT_CLOSING_SETTINGS,
        )
        db.session.commit()

        office = self._create_office(code='OFF-PART', name='Partial Office')

        total = round(2.0 * 210.0, 2)
        paid = round(total * 0.5, 2)

        payload = {
            'office_id': office.id,
            'reservation_date': datetime.utcnow().isoformat(),
            'karat': 21,
            'weight': 2.0,
            'price_per_gram': 210.0,
            'execution_price_per_gram': 210.0,
            'paid_amount': paid,
        }

        response = self.client.post(
            '/api/office-reservations',
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 201, msg=response.data)
        data = json.loads(response.data)

        self.assertIn('purchase_invoice_id', data)
        self.assertIsNone(data['purchase_invoice_id'])
        self.assertIn('payment_voucher_id', data)

        reservation_id = data['id']
        settle_payload = {
            'settlement_date': datetime.utcnow().isoformat(),
            'execution_price_per_gram': 210.0,
        }
        settle_resp = self.client.post(
            f'/api/office-reservations/{reservation_id}/settle',
            data=json.dumps(settle_payload),
            content_type='application/json',
        )
        self.assertEqual(settle_resp.status_code, 200, msg=settle_resp.data)
        settled = json.loads(settle_resp.data)

        inv = Invoice.query.get(settled['purchase_invoice_id'])
        self.assertIsNotNone(inv)
        self.assertEqual(inv.status, 'partially_paid')
        self.assertAlmostEqual(inv.amount_paid, paid)

    def test_reservation_enforces_office_supplier(self):
        """Reservation must reject mismatched supplier_id and use the office supplier automatically."""
        sale_invoice = self._create_sale_invoice(weight_grams=1.0, close_price=200.0)
        order = _upsert_weight_closing_order(
            sale_invoice,
            close_price_per_gram=200.0,
            settings=DEFAULT_WEIGHT_CLOSING_SETTINGS,
        )
        db.session.commit()

        office = self._create_office(code='OFF-SUP', name='Supplier Office')

        # Create a supplier explicitly that should NOT be accepted for the office
        external_supplier = Supplier(
            supplier_code='S-TEST-001',
            name='Test Supplier',
        )
        db.session.add(external_supplier)
        db.session.commit()

        payload = {
            'office_id': office.id,
            'reservation_date': datetime.utcnow().isoformat(),
            'karat': 21,
            'weight': 1.0,
            'price_per_gram': 200.0,
            'execution_price_per_gram': 200.0,
            'paid_amount': 200.0,
            'supplier_id': external_supplier.id,
        }

        response = self.client.post(
            '/api/office-reservations',
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

        # Retry without forcing supplier_id -> should succeed and auto-use office supplier
        payload.pop('supplier_id', None)
        response = self.client.post(
            '/api/office-reservations',
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 201, msg=response.data)
        data = json.loads(response.data)

        self.assertIsNone(data.get('purchase_invoice_id'))
        reservation_id = data['id']
        settle_payload = {
            'settlement_date': datetime.utcnow().isoformat(),
            'execution_price_per_gram': payload['execution_price_per_gram'],
        }
        settle_resp = self.client.post(
            f'/api/office-reservations/{reservation_id}/settle',
            data=json.dumps(settle_payload),
            content_type='application/json',
        )
        self.assertEqual(settle_resp.status_code, 200, msg=settle_resp.data)
        settled = json.loads(settle_resp.data)

        office_supplier = ensure_office_supplier(office)
        inv = Invoice.query.get(settled['purchase_invoice_id'])
        self.assertIsNotNone(inv)
        self.assertEqual(inv.supplier_id, office_supplier.id)

    def test_cash_settlement_endpoint_consumes_weight(self):
        sale_invoice = self._create_sale_invoice(weight_grams=1.0, close_price=370.0)
        _upsert_weight_closing_order(
            sale_invoice,
            close_price_per_gram=370.0,
            settings=DEFAULT_WEIGHT_CLOSING_SETTINGS,
        )
        db.session.commit()

        payload = {
            'cash_amount': 200.0,
            'price_per_gram': 370.0,
            'execution_type': 'expense',
        }

        response = self.client.post(
            '/api/weight-closing/cash-settlement',
            data=json.dumps(payload),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200, msg=response.data)
        body = json.loads(response.data)
        self.assertGreater(body['weight_consumed'], 0)
        self.assertAlmostEqual(body['cash_consumed'], payload['cash_amount'], places=2)

    def test_cash_settlement_tracks_price_difference(self):
        sale_invoice = self._create_sale_invoice(weight_grams=2.0, close_price=370.0)
        order = _upsert_weight_closing_order(
            sale_invoice,
            close_price_per_gram=370.0,
            settings=DEFAULT_WEIGHT_CLOSING_SETTINGS,
        )
        db.session.commit()

        payload = {
            'cash_amount': 800.0,
            'price_per_gram': 400.0,
            'execution_type': 'expense',
        }

        response = self.client.post(
            '/api/weight-closing/cash-settlement',
            data=json.dumps(payload),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200, msg=response.data)
        body = json.loads(response.data)
        self.assertGreater(body['difference_weight_total'], 0)

        refreshed_order = WeightClosingOrder.query.get(order.id)
        self.assertGreater(refreshed_order.executed_weight_main_karat, 0)

    def test_weight_profile_listing_endpoint(self):
        response = self.client.get('/api/weight-closing/profiles')
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.data)
        self.assertIn('profiles', body)
        keys = [profile['key'] for profile in body['profiles']]
        self.assertIn('cleaning', keys)

    def test_execute_weight_profile_consumes_open_orders(self):
        sale_invoice = self._create_sale_invoice(weight_grams=2.0, close_price=360.0)
        _upsert_weight_closing_order(
            sale_invoice,
            close_price_per_gram=360.0,
            settings=DEFAULT_WEIGHT_CLOSING_SETTINGS,
        )
        db.session.commit()

        payload = {
            'profile_key': 'cleaning',
            'cash_amount': 400.0,
            'price_per_gram': 400.0,
            'notes': 'تنفيذ نظافة اختبارية',
        }

        response = self.client.post(
            '/api/weight-closing/execute-profile',
            data=json.dumps(payload),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200, msg=response.data)
        body = json.loads(response.data)
        self.assertIn('journal_entry', body)
        self.assertIn('weight_consumption', body)
        self.assertGreater(body['weight_main_karat'], 0)
        self.assertAlmostEqual(body['cash_amount'], payload['cash_amount'])
        self.assertGreater(body['weight_consumption']['weight_consumed'], 0)

        journal_entry = JournalEntry.query.get(body['journal_entry']['id'])
        self.assertIsNotNone(journal_entry)
        lines = JournalEntryLine.query.filter_by(journal_entry_id=journal_entry.id).all()
        self.assertGreaterEqual(len(lines), 2)

        cleaning_account = Account.query.filter_by(account_number='5110').first()
        self.assertIsNotNone(cleaning_account)
        self.assertTrue(
            any((line.cash_debit or 0.0) > 0 and line.account_id == cleaning_account.id for line in lines)
        )
        sale_invoice = self._create_sale_invoice(weight_grams=2.0, close_price=370.0)
        order = _upsert_weight_closing_order(
            sale_invoice,
            close_price_per_gram=370.0,
            settings=DEFAULT_WEIGHT_CLOSING_SETTINGS,
        )
        db.session.commit()

        payload = {
            'cash_amount': 800.0,
            'price_per_gram': 400.0,
            'execution_type': 'expense',
        }

        response = self.client.post(
            '/api/weight-closing/cash-settlement',
            data=json.dumps(payload),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200, msg=response.data)
        body = json.loads(response.data)
        self.assertGreater(body['difference_weight_total'], 0)

        refreshed_order = WeightClosingOrder.query.get(order.id)
        self.assertGreater(refreshed_order.executed_weight_main_karat, 0)



if __name__ == '__main__':
    unittest.main()
