"""Utilities to ensure each office has a dedicated accounting sub-account."""
from __future__ import annotations

from typing import Optional

from models import db, Account, Office

# Default parent for closing offices: under raw-gold suppliers (per current COA).
DEFAULT_PARENT_ACCOUNT_NUMBER = '2200'
DEFAULT_PARENT_ACCOUNT_NAME = 'موردي الذهب الخام'


def _digits_only(value: str) -> str:
    return ''.join(ch for ch in (value or '') if ch.isdigit())


def _extract_office_suffix(office: Office) -> str:
    if office.office_code and '-' in office.office_code:
        return office.office_code.split('-')[-1]
    if office.office_code:
        return office.office_code
    if office.id:
        return f"{int(office.id):06d}"
    return '000000'


def ensure_office_parent_account(parent_account_number: str = DEFAULT_PARENT_ACCOUNT_NUMBER) -> Account:
    # 1) Try the requested parent directly (supports legacy charts).
    requested = str(parent_account_number or '').strip()
    if requested:
        parent = Account.query.filter_by(account_number=requested).first()
        if parent:
            return parent

    # 2) Fallback to current COA roots (new charts use 220/2200 and 210/2100).
    for fallback_number in (
        '2200',
        '220',
        '2100',  # supplier posting group (preferred)
        '210',
        '21',
        '21100',
        '211',
    ):
        parent = Account.query.filter_by(account_number=fallback_number).first()
        if parent:
            return parent

    # 3) Bootstrap a minimal supplier hierarchy so office creation never hard-fails.
    # Prefer 220/2200 (raw gold suppliers). If that fails, create 210/2100.

    category_22 = Account.query.filter_by(account_number='22').first()
    category_220 = Account.query.filter_by(account_number='220').first()
    category_2200 = Account.query.filter_by(account_number='2200').first()

    if category_2200:
        return category_2200

    if category_220 and not category_2200:
        category_2200 = Account(
            account_number='2200',
            name='حسابات موردو الذهب الخام',
            type=(category_220.type or 'Liability'),
            transaction_type='cash',
            tracks_weight=False,
            parent_id=category_220.id,
        )
        db.session.add(category_2200)
        db.session.flush()
        return category_2200

    if category_22 and not category_220:
        category_220 = Account(
            account_number='220',
            name='موردو الذهب الخام',
            type='Liability',
            transaction_type='cash',
            tracks_weight=False,
            parent_id=category_22.id,
        )
        db.session.add(category_220)
        db.session.flush()
        category_2200 = Account(
            account_number='2200',
            name='حسابات موردو الذهب الخام',
            type='Liability',
            transaction_type='cash',
            tracks_weight=False,
            parent_id=category_220.id,
        )
        db.session.add(category_2200)
        db.session.flush()
        return category_2200

    category_210 = Account.query.filter_by(account_number='210').first()
    if not category_210:
        category_210 = Account(
            account_number='210',
            name='حسابات الموردين',
            type='Liability',
            transaction_type='cash',
            tracks_weight=False,
            parent_id=None,
        )
        db.session.add(category_210)
        db.session.flush()

    category_2100 = Account.query.filter_by(account_number='2100').first()
    if not category_2100:
        category_2100 = Account(
            account_number='2100',
            name='حسابات موردو ذهب',
            type=(category_210.type or 'Liability'),
            transaction_type='cash',
            tracks_weight=False,
            parent_id=category_210.id,
        )
        db.session.add(category_2100)
        db.session.flush()

    return category_2100


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
            # If chart changed, re-parent office account under the resolved parent.
            parent = ensure_office_parent_account(parent_account_number)
            if parent and existing.parent_id != parent.id:
                existing.parent_id = parent.id
            # Office accounts participate in dual (cash+weight) entries.
            # Ensure they can track weight so stored balances stay correct.
            changed = False
            if getattr(existing, 'transaction_type', None) != 'both':
                existing.transaction_type = 'both'
                changed = True
            if not bool(getattr(existing, 'tracks_weight', False)):
                existing.tracks_weight = True
                changed = True
            if changed or (parent and existing.parent_id == parent.id):
                db.session.add(existing)
                db.session.flush()
            return existing

    parent = ensure_office_parent_account(parent_account_number)

    # Create office posting accounts the same way we create supplier accounts:
    # sequential under the resolved parent category.
    from account_number_generator import get_next_account_number, get_next_party_account_number

    parent_digits = _digits_only(str(getattr(parent, 'account_number', '') or ''))
    if len(parent_digits) == 3:
        next_number = get_next_party_account_number(parent_digits)
    else:
        next_number = get_next_account_number(parent_digits, use_spacing=False)

    account_number = _digits_only(str(next_number))

    account = Account.query.filter_by(account_number=account_number).first()
    if not account:
        account = Account(
            account_number=account_number,
            name=office.name or 'مكتب',
            type=(parent.type or 'Liability'),
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
