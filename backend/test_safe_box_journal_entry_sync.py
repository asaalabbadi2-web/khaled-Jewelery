import pytest
from app import app as _app
from models import db, SafeBox, SafeBoxTransaction, JournalEntry, JournalEntryLine, Account


@pytest.fixture()
def app():
    _app.config['TESTING'] = True
    _app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    with _app.app_context():
        db.create_all()
        yield _app
        db.session.rollback()
        db.drop_all()


def _make_account(name, number, acc_type='asset'):
    a = Account(name=name, account_number=number, account_type=acc_type, type=acc_type)
    db.session.add(a)
    db.session.flush()
    return a


def test_manual_posted_journal_entry_creates_safe_box_transactions(app):
    from routes import _rebuild_safe_box_transactions_for_journal_entry

    with app.app_context():
        acc = _make_account('Main Cash', '1000', 'asset')
        sb = SafeBox(name='Main Cash Safe', safe_type='cash', account_id=acc.id, is_active=True)
        db.session.add(sb)
        db.session.flush()

        je = JournalEntry(
            description='Manual cash in',
            is_draft=False,
            reference_type=None,
        )
        # Schema varies; keep posted true when field exists.
        if hasattr(je, 'is_posted'):
            je.is_posted = True
        db.session.add(je)
        db.session.flush()

        line = JournalEntryLine(
            journal_entry_id=je.id,
            account_id=acc.id,
            cash_debit=100.0,
            cash_credit=0.0,
        )
        db.session.add(line)
        db.session.flush()

        _rebuild_safe_box_transactions_for_journal_entry(je, [line], created_by='test')
        db.session.flush()

        txs = SafeBoxTransaction.query.filter_by(ref_type='journal_entry', ref_id=je.id).all()
        assert len(txs) == 1
        assert txs[0].safe_box_id == sb.id
        assert txs[0].direction == 'in'
        assert float(txs[0].amount_cash) == 100.0

        # Idempotent: running again does not create duplicates
        _rebuild_safe_box_transactions_for_journal_entry(je, [line], created_by='test')
        db.session.flush()
        txs2 = SafeBoxTransaction.query.filter_by(ref_type='journal_entry', ref_id=je.id).all()
        assert len(txs2) == 1
