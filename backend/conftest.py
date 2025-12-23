import os
import pytest

# Ensure backend package is importable
import app as flask_app_module

from app import app, reset_database
from models import db, Account, Supplier, Customer, Employee, Invoice
from datetime import datetime


@pytest.fixture(scope='session', autouse=True)
def initialize_db():
    """Reset DB and seed minimal chart-of-accounts and basic data for tests.

    This fixture runs once per pytest session. It creates required accounts
    with specific IDs used by unit tests, plus a sample supplier/customer/employee.
    """
    # Make sure we run inside the Flask app context
    with app.app_context():
        # reset the database to a clean state
        try:
            reset_database()
        except Exception:
            # best-effort: if reset_database isn't available, fallback to create_all
            db.session.remove()
            db.drop_all()
            db.create_all()

        # Seed essential accounts with fixed IDs used in tests
        # Use explicit ids so tests referencing account numbers work reliably
        accounts = [
            (15, 'صندوق النقدية', 'Asset', False),
            (400, 'مبيعات ذهب جديد', 'Revenue', True),
            (521, 'تكلفة مبيعات الذهب', 'Expense', True),
            (1200, 'مخزون ذهب عيار 24', 'Asset', True),
            (1220, 'مخزون ذهب عيار 21', 'Asset', True),
        ]

        for acc_id, name, acc_type, tracks_weight in accounts:
            existing = Account.query.get(acc_id)
            if existing:
                existing.name = name
                existing.type = acc_type
                existing.tracks_weight = tracks_weight
            else:
                a = Account(id=acc_id, account_number=str(acc_id), name=name, type=acc_type, tracks_weight=tracks_weight)
                # initialize balances to known values if needed
                if acc_id == 15:
                    a.balance_cash = 10000.0
                db.session.add(a)

        # Seed a supplier with id=1 (some integration tests expect supplier 1)
        if not Supplier.query.get(1):
            s = Supplier(id=1, supplier_code='S-000001', name='لازوردي')
            db.session.add(s)

        # Seed a sample customer and employee for tests
        if not Customer.query.first():
            c = Customer(customer_code='C-000001', name='عميل اختبار', phone='0500000001', email='test@example.com')
            db.session.add(c)

        if not Employee.query.first():
            e = Employee(employee_code='E-000001', name='موظف اختبار', is_active=True)
            db.session.add(e)

        db.session.commit()


@pytest.fixture
def customer_id():
    with app.app_context():
        c = Customer.query.first()
        return c.id if c else None


@pytest.fixture
def original_invoice_id():
    """Create a minimal invoice to be used as 'original' for return tests."""
    with app.app_context():
        inv = Invoice(invoice_type_id=1, invoice_type='بيع', date=datetime.now(), total=1000.0)
        db.session.add(inv)
        db.session.commit()
        return inv.id


def pytest_collection_modifyitems(config, items):
    """Skip integration-like HTTP tests unless RUN_SERVER_TESTS env is set.

    Tests that rely on a running HTTP server (the files starting with
    `test_invoices.py` and `test_supplier_purchase.py`) are skipped by default.
    Set RUN_SERVER_TESTS=1 to run them.
    """
    run_server = os.getenv('RUN_SERVER_TESTS') == '1'
    if run_server:
        return

    skip_marker = pytest.mark.skip(reason="Integration server tests skipped; set RUN_SERVER_TESTS=1 to enable")
    skip_files = {'test_invoices.py', 'test_supplier_purchase.py', 'test_invoice.py', 'test_advance_accounts.py'}
    for item in items:
        if item.fspath.basename in skip_files:
            item.add_marker(skip_marker)
