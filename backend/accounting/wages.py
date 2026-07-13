from __future__ import annotations

from models import db, Account
from accounting.mappings import get_account_id_by_number, _ACCOUNT_NUMBER_CACHE


def _ensure_manufacturing_wage_expense_account() -> int | None:
    """Find or create the manufacturing wage expense account (510) and return its ID."""
    target_number = '510'
    cached = get_account_id_by_number(target_number)
    if cached:
        return cached

    parent = Account.query.filter_by(account_number='51').first()
    account = Account(
        account_number=target_number,
        name='مصروفات أجور المصنعية',
        type='expense',
        transaction_type='cash',
        tracks_weight=False,
        parent_id=parent.id if parent else None,
    )
    db.session.add(account)
    db.session.commit()
    _ACCOUNT_NUMBER_CACHE[target_number] = account.id
    return account.id


def _ensure_gold24k_commission_revenue_account() -> int | None:
    """Find or create إيرادات عمولة السداد بذهب صافي under 41 (إيرادات النشاط).

    Uses name-first lookup so the account is found regardless of which number
    was assigned on first creation (avoids clashes across dev/prod DBs).
    Production account number: 4110.
    """
    by_number = Account.query.filter_by(account_number='4110').first()
    if by_number:
        return by_number.id

    acct_name = 'إيرادات عمولة السداد بذهب صافي'
    by_name = Account.query.filter_by(name=acct_name).first()
    if by_name:
        return by_name.id

    parent = Account.query.filter_by(account_number='41').first()
    if not parent:
        parent = Account.query.filter_by(account_number='4').first()
    chosen_number = None
    for candidate in ('4110', '4111', '4112', '4113', '4120'):
        if not Account.query.filter_by(account_number=candidate).first():
            chosen_number = candidate
            break
    if not chosen_number:
        chosen_number = '4110'

    account = Account(
        account_number=chosen_number,
        name=acct_name,
        type='revenue',
        transaction_type='cash',
        tracks_weight=False,
        parent_id=parent.id if parent else None,
    )
    db.session.add(account)
    db.session.flush()
    return account.id
