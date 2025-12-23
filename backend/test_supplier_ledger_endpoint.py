#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Tests for the supplier ledger endpoint."""

import unittest
from datetime import datetime

from flask import Flask

from models import db, Supplier, Account, JournalEntry, JournalEntryLine
from routes import api as api_blueprint


class SupplierLedgerEndpointTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask(__name__)
        cls.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
        cls.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(cls.app)
        cls.app.register_blueprint(api_blueprint, url_prefix='/api')

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()

        self.supplier = Supplier(
            supplier_code='S-000001',
            name='Test Supplier',
        )
        self.account = Account(
            account_number='2010',
            name='Accounts Payable',
            type='Liability',
            transaction_type='both',
            tracks_weight=True,
        )
        db.session.add_all([self.supplier, self.account])
        db.session.commit()

        self._add_entry(datetime(2025, 1, 1, 10, 0), cash_debit=500.0, gold_21k=5.0)
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _add_entry(self, entry_date: datetime, cash_debit: float, gold_21k: float = 0.0):
        entry_number = f'JE-TEST-{JournalEntry.query.count() + 1:04d}'
        entry = JournalEntry(
            entry_number=entry_number,
            date=entry_date,
            description='Seed entry',
        )
        line = JournalEntryLine(
            journal_entry=entry,
            supplier=self.supplier,
            account=self.account,
            cash_debit=cash_debit,
            debit_21k=gold_21k,
        )
        db.session.add_all([entry, line])
        db.session.commit()
        return entry

    def test_ledger_endpoint_returns_summary_and_movements(self):
        resp = self.client.get(f'/api/suppliers/{self.supplier.id}/ledger')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()

        self.assertIn('summary', data)
        self.assertIn('pagination', data)
        self.assertIn('movements', data)
        self.assertEqual(data['summary']['total_debits']['cash'], 500.0)
        self.assertEqual(data['pagination']['total_items'], 1)
        self.assertGreater(len(data['movements']), 0)
        movement = data['movements'][0]
        self.assertEqual(movement['account_name'], self.account.name)
        self.assertAlmostEqual(movement['gold_21k_debit'], 5.0)

    def test_ledger_endpoint_with_date_filters(self):
        # Filter with a start date after the existing entry -> expect empty result
        resp = self.client.get(
            f'/api/suppliers/{self.supplier.id}/ledger',
            query_string={'date_from': '2025-02-01'},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['pagination']['total_items'], 0)
        self.assertEqual(data['movements'], [])

    def test_ledger_endpoint_pagination(self):
        self._add_entry(datetime(2025, 2, 1, 12, 0), cash_debit=250.0, gold_21k=2.0)
        resp = self.client.get(
            f'/api/suppliers/{self.supplier.id}/ledger',
            query_string={'per_page': 1},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['pagination']['total_pages'], 2)
        self.assertEqual(data['pagination']['total_items'], 2)


if __name__ == '__main__':
    unittest.main()
