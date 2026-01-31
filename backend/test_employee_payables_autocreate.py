import pytest

from app import app
from models import Account, db

from employee_account_helpers import (
    EMPLOYEE_PAYABLES_ROOT_NUMBER,
    ensure_employee_group_accounts,
    get_or_create_employee_payables_accounts,
)


def _get_by_number(num: str):
    return Account.query.filter_by(account_number=str(num)).first()


def test_employee_payables_accounts_created_under_240_groups():
    with app.app_context():
        # Ensure grouping structure exists (should create 240 + 2400/2410/2420 on fresh test DB).
        ensure_employee_group_accounts(created_by='pytest')

        root = _get_by_number(EMPLOYEE_PAYABLES_ROOT_NUMBER)
        assert root is not None
        assert (root.name or '').strip() != ''

        # Expected detail groups
        g_salary = _get_by_number('2400')
        g_comm = _get_by_number('2410')
        g_eos = _get_by_number('2420')

        assert g_salary is not None
        assert g_comm is not None
        assert g_eos is not None

        assert g_salary.parent_id == root.id
        assert g_comm.parent_id == root.id
        assert g_eos.parent_id == root.id

        # Create/ensure per-employee accounts
        accounts = get_or_create_employee_payables_accounts('موظف اختبار 240', created_by='pytest')
        assert len(accounts) == 3

        parent_ids = {a.parent_id for a in accounts}
        assert parent_ids == {g_salary.id, g_comm.id, g_eos.id}

        # Each should have a memo/weight parallel account linked.
        for a in accounts:
            assert getattr(a, 'memo_account_id', None) is not None
            memo = Account.query.get(int(a.memo_account_id))
            assert memo is not None
            assert str(memo.account_number) == f"7{a.account_number}"

        db.session.commit()
