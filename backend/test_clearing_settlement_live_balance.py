from datetime import datetime

import routes
from app import app
from models import Account, SafeBox, SafeBoxTransaction, Voucher, db


def _create_safe_box(name: str, safe_type: str, account_number: str) -> SafeBox:
    account = Account(
        account_number=account_number,
        name=f'حساب {name}',
        type='Asset',
        balance_cash=0.0,
    )
    db.session.add(account)
    db.session.flush()

    safe_box = SafeBox(
        name=name,
        safe_type=safe_type,
        account_id=account.id,
        is_active=True,
    )
    db.session.add(safe_box)
    db.session.flush()
    return safe_box


def test_clearing_settlement_uses_live_balance(monkeypatch):
    with app.app_context():
        clearing_safe = _create_safe_box('مستحقات اختبار', 'clearing', '9101')
        bank_safe = _create_safe_box('بنك اختبار', 'bank', '9102')

        # Create invoice_payment transaction so due_amount > 0
        ip_tx = SafeBoxTransaction(
            safe_box_id=clearing_safe.id,
            ref_type='invoice_payment',
            direction='in',
            amount_cash=250.0,
        )
        db.session.add(ip_tx)
        db.session.commit()

        monkeypatch.setattr(
            routes,
            'live_balances_by_account_ids',
            lambda ids: {
                int(account_id): {'cash': 250.0 if int(account_id) == clearing_safe.account_id else 0.0}
                for account_id in ids
            },
        )
        monkeypatch.setattr(routes, 'generate_voucher_number', lambda *args, **kwargs: 'ADJ-TEST-LIVE-0001')
        monkeypatch.setattr(routes, 'create_journal_entry_from_voucher', lambda voucher: None)
        monkeypatch.setattr(routes, '_append_safe_transactions_for_voucher', lambda voucher, created_by=None: None)

        result = routes._create_clearing_settlement_voucher(
            clearing_safe_box_id=clearing_safe.id,
            bank_safe_box_id=bank_safe.id,
            gross_amount=200.0,
            fee_amount=0.0,
            settlement_dt=datetime.now(),
            created_by='pytest',
        )

        assert result['success'] is True
        assert result['voucher']['voucher_number'] == 'ADJ-TEST-LIVE-0001'
        assert result['balances']['clearing_account_cash'] == 250.0

        db.session.rollback()


def test_pending_transactions_skip_settled_rows_without_invoice_payment_id(auth_headers):
    with app.app_context():
        clearing_safe = _create_safe_box('مستحقات معلقة', 'clearing', '9103')
        db.session.commit()
        clearing_safe_id = clearing_safe.id

        pending_tx = SafeBoxTransaction(
            safe_box_id=clearing_safe.id,
            ref_type='invoice_payment',
            direction='in',
            amount_cash=80.0,
            invoice_payment_id=None,
            notes='pending tx without invoice_payment_id',
        )
        db.session.add(pending_tx)
        db.session.flush()

        voucher = Voucher(
            voucher_number='ADJ-TEST-PENDING-0001',
            voucher_type='adjustment',
            date=datetime.now(),
            description='تسوية اختبارية',
            reference_type='clearing_settlement',
            status='approved',
            created_by='pytest',
            approved_by='pytest',
            approved_at=datetime.now(),
            amount_cash=80.0,
            amount_gold=0.0,
        )
        db.session.add(voucher)
        db.session.flush()

        settled_marker = SafeBoxTransaction(
            safe_box_id=clearing_safe.id,
            ref_type='voucher',
            ref_id=voucher.id,
            direction='out',
            amount_cash=80.0,
            notes=f'per_tx:ip_{pending_tx.id}',
        )
        db.session.add(settled_marker)
        db.session.commit()

    with app.test_client() as client:
        response = client.get(
            f'/api/clearing/settlements/pending-transactions?clearing_safe_box_id={clearing_safe_id}',
            headers=auth_headers,
        )

    assert response.status_code == 200
    data = response.get_json()
    assert data['pending_count'] == 0
    assert data['transactions'] == []