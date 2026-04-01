"""Utilities to ensure each office has a dedicated accounting sub-account."""
from __future__ import annotations

from typing import Optional

from models import db, Account, Office

# Default parent for closing offices: under manufactured-gold suppliers (per current COA).
DEFAULT_PARENT_ACCOUNT_NUMBER = '2100'
DEFAULT_PARENT_ACCOUNT_NAME = 'حسابات موردو الذهب المشغول'


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

    # 2) Fallback to current COA roots (new charts use 210/2100 for manufactured gold).
    for fallback_number in (
        '2100',  # manufactured gold posting group (preferred)
        '210',
        '21',
        '2200',  # raw gold — only if no manufactured group found
        '220',
        '21100',
        '211',
    ):
        parent = Account.query.filter_by(account_number=fallback_number).first()
        if parent:
            return parent

    # 3) Bootstrap a minimal supplier hierarchy so office creation never hard-fails.
    # Prefer 210/2100 (manufactured gold suppliers). If that fails, create 220/2200.

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


def _ensure_memo_account_for_office_account(financial_or_bridge: Account) -> Account:
    """Ensure a memo (weight) account exists for the office posting account.

    Office accounts historically used transaction_type='both'. The standard Account
    helper `create_parallel_account()` intentionally skips 'both' accounts, so we
    implement a lightweight memo-number rule here:

      memo_number = '7' + digits(financial.account_number)

    We also mirror the parent relationship when possible.
    """

    if not financial_or_bridge:
        raise ValueError('account is required')

    # If already linked and valid, reuse.
    try:
        existing = Account.query.get(int(financial_or_bridge.memo_account_id)) if financial_or_bridge.memo_account_id else None
    except Exception:
        existing = None
    if existing and existing.transaction_type == 'gold' and bool(getattr(existing, 'tracks_weight', False)):
        return existing

    def _digits_only_local(value: str) -> str:
        return ''.join(ch for ch in str(value or '').strip() if ch.isdigit())

    fin_no = _digits_only_local(getattr(financial_or_bridge, 'account_number', None) or '')
    if not fin_no:
        raise ValueError('office account_number must contain digits to create memo account')

    memo_no = f"7{fin_no}"

    memo = Account.query.filter_by(account_number=memo_no).first()

    # Determine desired parent memo id by mirroring the financial parent.
    desired_parent_id = None
    try:
        if getattr(financial_or_bridge, 'parent_id', None):
            parent = Account.query.get(int(financial_or_bridge.parent_id))
            if parent:
                if getattr(parent, 'memo_account_id', None):
                    desired_parent_id = int(parent.memo_account_id)
                else:
                    # Try to create a memo for the parent when possible.
                    try:
                        parent_parallel = parent.create_parallel_account()
                        if parent_parallel:
                            desired_parent_id = int(parent_parallel.id)
                    except Exception:
                        desired_parent_id = None
    except Exception:
        desired_parent_id = None

    if memo:
        memo.transaction_type = 'gold'
        memo.tracks_weight = True
        if desired_parent_id and memo.parent_id != desired_parent_id:
            memo.parent_id = desired_parent_id
    else:
        memo = Account(
            account_number=memo_no,
            name=f"{financial_or_bridge.name} وزني",
            type=financial_or_bridge.type,
            transaction_type='gold',
            tracks_weight=True,
            parent_id=desired_parent_id,
        )
        db.session.add(memo)
        db.session.flush()

    # Link both ways.
    financial_or_bridge.memo_account_id = memo.id
    memo.memo_account_id = financial_or_bridge.id
    db.session.add(financial_or_bridge)
    db.session.add(memo)
    db.session.flush()

    return memo


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

            # Ensure memo account exists even for legacy 'both' office accounts.
            try:
                _ensure_memo_account_for_office_account(existing)
            except Exception:
                pass
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

    # Ensure memo account exists for the newly created office account.
    try:
        _ensure_memo_account_for_office_account(account)
    except Exception:
        pass

    office.account_category_id = account.id
    db.session.add(office)

    if auto_commit:
        db.session.commit()

    return account
