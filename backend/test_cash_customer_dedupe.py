#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unit test: POST /customers should not duplicate the cash customer.

Scenario:
- Frontend invoices may auto-create "عميل نقدي" when no customer is selected.
- If the client cache doesn't include it yet, it may call creation again.
- Backend should treat creating "عميل نقدي" as idempotent and reuse the existing row.
"""

import json
import os
import sys
import unittest

from flask import Flask
from flask import g
from flask import request

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

import recurring_journal_system  # noqa: F401  # Ensure recurring tables exist in metadata

from models import db  # noqa: E402
from routes import api as api_blueprint  # noqa: E402


class CashCustomerDedupeTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask(__name__)
        cls.app.config['TESTING'] = True
        cls.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
        cls.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(cls.app)
        cls.app.register_blueprint(api_blueprint, url_prefix='/api')

        class _AdminUser:
            is_admin = True
            is_active = True

            def has_permission(self, _code: str) -> bool:
                return True

        @cls.app.before_request
        def _inject_admin_user():
            # Satisfy the global auth enforcement in routes.py
            if request.path.startswith('/api'):
                g.current_user = _AdminUser()

    def setUp(self):
        with self.app.app_context():
            db.drop_all()
            db.create_all()

    def test_cash_customer_create_is_idempotent(self):
        with self.app.app_context():
            client = self.app.test_client()

            payload = {
                'name': 'عميل نقدي',
                'notes': 'تم إنشاؤه تلقائياً للاستخدام كعميل نقدي',
                # Keep the test isolated from chart-of-accounts setup.
                'ensure_accounts': False,
            }

            r1 = client.post(
                '/api/customers',
                data=json.dumps(payload),
                content_type='application/json',
            )
            self.assertEqual(r1.status_code, 201)
            d1 = r1.get_json() or {}
            self.assertTrue(d1.get('id'))

            r2 = client.post(
                '/api/customers',
                data=json.dumps(payload),
                content_type='application/json',
            )
            self.assertEqual(r2.status_code, 201)
            d2 = r2.get_json() or {}
            self.assertEqual(d1.get('id'), d2.get('id'))

            # Verify only one row exists.
            from models import Customer  # local import

            cash = Customer.query.filter(Customer.name == 'عميل نقدي').all()
            self.assertEqual(len(cash), 1)


if __name__ == '__main__':
    unittest.main()
