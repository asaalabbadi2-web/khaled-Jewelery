"""Utilities to ensure each office has a dedicated accounting sub-account."""
from __future__ import annotations

from typing import Optional

from models import db, Account, Office

DEFAULT_PARENT_ACCOUNT_NUMBER = '21110'
DEFAULT_PARENT_ACCOUNT_NAME = 'مكاتب التسكير'


def _extract_office_suffix(office: Office) -> str:
    if office.office_code and '-' in office.office_code:
        return office.office_code.split('-')[-1]
    if office.office_code:
        return office.office_code
    if office.id:
        return f"{int(office.id):06d}"
    return '000000'


def ensure_office_parent_account(parent_account_number: str = DEFAULT_PARENT_ACCOUNT_NUMBER) -> Account:
    parent = Account.query.filter_by(account_number=parent_account_number).first()
    if not parent:
        raise ValueError(
            f'الحساب التجميعي للموردين {parent_account_number} غير موجود. '
            'يرجى إنشاؤه أولاً.'
        )
    return parent


def ensure_office_account(
    office: Office,
    *,
    parent_account_number: str = DEFAULT_PARENT_ACCOUNT_NUMBER,
    auto_commit: bool = False,
) -> Account:
    """Ensure the office has a dedicated accounting sub-account and return it."""
    if not office:
        raise ValueError('office is required to ensure accounting linkage')

    if office.account_category_id:
        existing = Account.query.get(office.account_category_id)
        if existing:
            return existing

    parent = ensure_office_parent_account(parent_account_number)

    suffix = _extract_office_suffix(office)
    # Use same numbering pattern as suppliers: 211XX (where XX is from office code)
    account_number = f"{parent.account_number}{suffix}"

    account = Account.query.filter_by(account_number=account_number).first()
    if not account:
        # اسم الحساب = اسم المكتب فقط (بدون كود OFF)
        account = Account(
            account_number=account_number,
            name=office.name or 'مكتب',
            type=parent.type,
            transaction_type='both',
            tracks_weight=True,
            parent_id=parent.id,
        )
        db.session.add(account)
        db.session.flush()

    office.account_category_id = account.id
    db.session.add(office)

    if auto_commit:
        db.session.commit()

    return account
