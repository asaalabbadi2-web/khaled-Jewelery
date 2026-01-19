#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Helpers for creating an employee cash safe box + linked accounting account.

Requirement:
- الخزائن النقدية تحت "صناديق الموظفين النقدية (عهد)"

Implementation (matches the current chart-of-accounts):
- Ensure a grouping account exists: 1100001 "صناديق الموظفين النقدية (عهد)" under cash account "1100" (or "110").
- Create a dedicated account per employee under 1100001 (11000010, 11000011, ...).
- Create a SafeBox of type 'cash' linked to that account.
"""

from models import Account, SafeBox, db
from account_number_generator import get_next_account_number


def ensure_employee_cash_group_account(created_by: str = 'system') -> Account | None:
    """Ensure the grouping account for employee cash safes exists (1100001)."""
    group = Account.query.filter_by(account_number='1100001').first()
    if group:
        # Keep naming consistent with requested structure.
        if (group.name or '').strip() != 'صناديق الموظفين النقدية (عهد)':
            group.name = 'صناديق الموظفين النقدية (عهد)'
            db.session.flush()
        return group

    parent = Account.query.filter_by(account_number='1100').first()
    if not parent:
        parent = Account.query.filter_by(account_number='110').first()
    if not parent:
        return None

    group = Account(
        account_number='1100001',
        name='صناديق الموظفين النقدية (عهد)',
        type='asset',
        transaction_type='cash',
        tracks_weight=False,
        parent_id=parent.id,
    )
    db.session.add(group)
    db.session.flush()
    return group


def _next_child_number_under_group(group_account: Account) -> str:
    """Generate next account_number under a group account using chart numbering rules."""
    # Uses existing rules: for a 7-digit parent like 1100001, children are 11000010..11000019.
    candidate = get_next_account_number(str(group_account.account_number))
    # Extra guard for uniqueness (rare, but safe)
    while Account.query.filter_by(account_number=str(candidate)).first() is not None:
        candidate = str(int(candidate) + 1)
    return str(candidate)


def create_employee_cash_safe(employee_name: str, created_by: str = 'system', employee_code: str | None = None):
    """Create (Account + SafeBox) for an employee cash custody safe.

    Returns:
        tuple[Account, SafeBox]
    """

    group = ensure_employee_cash_group_account(created_by=created_by)
    if not group:
        raise ValueError('تعذر تحديد/إنشاء الحساب التجميعي لصناديق الموظفين النقدية (1100001).')

    acc_number = _next_child_number_under_group(group)
    label = employee_name
    if employee_code:
        label = f'{employee_name} ({employee_code})'

    account = Account(
        account_number=acc_number,
        name=f'صندوق الموظف {label}',
        type='asset',
        transaction_type='cash',
        tracks_weight=False,
        parent_id=group.id,
    )
    db.session.add(account)
    db.session.flush()

    safe = SafeBox(
        name=f'صندوق الموظف {employee_name}',
        name_en=None,
        safe_type='cash',
        account_id=int(account.id),
        karat=None,
        is_active=True,
        is_default=False,
        notes='صندوق نقدية خاص بالموظف',
        created_by=created_by,
    )
    db.session.add(safe)
    db.session.flush()

    return account, safe
