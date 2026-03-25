import json

import pytest
from app import app as _app
from models import (
    Account,
    JournalEntry,
    JournalEntryLine,
    SafeBox,
    SafeBoxTransaction,
    Voucher,
    VoucherAccountLine,
    db,
)


@pytest.fixture()
def app():
    _app.config['TESTING'] = True
    _app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    with _app.app_context():
        db.create_all()
        yield _app
        db.session.rollback()
        db.drop_all()


def _make_account(name: str, number: str, acc_type: str = 'asset') -> Account:
    acc = Account(name=name, account_number=number, account_type=acc_type, type=acc_type)
    db.session.add(acc)
    db.session.flush()
    return acc


def test_append_safe_transactions_prefers_journal_entry_lines(app):
    """Regression guard:

    Even if VoucherAccountLine uses a non-safe account (drift), we must still create
    SafeBoxTransaction rows based on the linked JournalEntry lines (source of truth).
    """

    from routes import _append_safe_transactions_for_voucher

    with app.app_context():
        safe_acc = _make_account('Cash Safe Account', '1000', 'asset')
        other_cash = _make_account('Other Cash Account', '1001', 'asset')

        safe = SafeBox(name='Main Safe', safe_type='cash', account_id=safe_acc.id, is_active=True)
        db.session.add(safe)
        db.session.flush()

        voucher = Voucher(
            voucher_number='P-TEST-00001',
            voucher_type='payment',
            date=None,
            description='Test payment',
            created_by='test',
            status='approved',
            notes=json.dumps({'invoice_payment_id': 123, 'payment_method_id': 7}),
        )
        db.session.add(voucher)
        db.session.flush()

        # Voucher lines drift: use a non-safe account.
        db.session.add(
            VoucherAccountLine(
                voucher_id=voucher.id,
                account_id=other_cash.id,
                line_type='credit',
                amount_type='cash',
                amount=150000.0,
                description='Drifted line',
            )
        )
        db.session.flush()

        je = JournalEntry(
            entry_number='JE-TEST-00001',
            date=None,
            description='Posted from voucher',
            reference_type='voucher',
            reference_id=voucher.id,
            created_by='test',
        )
        if hasattr(je, 'is_posted'):
            je.is_posted = True
        db.session.add(je)
        db.session.flush()

        # Actual posting hits the SafeBox account.
        db.session.add(
            JournalEntryLine(
                journal_entry_id=je.id,
                account_id=safe_acc.id,
                cash_debit=0.0,
                cash_credit=150000.0,
            )
        )
        db.session.flush()

        voucher.journal_entry_id = je.id
        db.session.add(voucher)
        db.session.flush()

        created = _append_safe_transactions_for_voucher(voucher, created_by='test')
        db.session.flush()

        assert len(created) == 1
        tx = created[0]
        assert tx.safe_box_id == safe.id
        assert tx.direction == 'out'
        assert float(tx.amount_cash or 0.0) == 150000.0
        assert tx.ref_type == 'invoice_payment'
        assert int(tx.invoice_payment_id) == 123

        # Idempotent.
        created2 = _append_safe_transactions_for_voucher(voucher, created_by='test')
        db.session.flush()
        assert created2 == []
        assert SafeBoxTransaction.query.filter_by(ref_id=voucher.id).count() == 1
