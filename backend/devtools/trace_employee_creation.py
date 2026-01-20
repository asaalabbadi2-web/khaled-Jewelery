#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Trace what was created for an employee.

Prints:
- Employee record + linked personal Account
- Linked cash/gold SafeBox (if any) + their linked Accounts
- Any Accounts that match the employee name and common auto-generated prefixes

Usage:
  backend/devtools/trace_employee_creation.py --name "سعيد"
  backend/devtools/trace_employee_creation.py --code "EMP-2026-0001"

Notes:
- This does not modify data.
- It queries the current DATABASE_URL (same as app.py).
"""

import os
import sys
import argparse

from typing import Optional

# When executed from backend/devtools, ensure backend/ is importable.
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app import app  # noqa: E402
from models import db, Employee, Account, SafeBox  # noqa: E402


def _fmt(v):
    return '' if v is None else str(v)


def _print_account(prefix: str, acc: Optional[Account]):
    if not acc:
        print(f"- {prefix}: (لا يوجد)")
        return
    created_at = getattr(acc, 'created_at', None)
    created_at_str = created_at.isoformat() if created_at else ''
    print(
        f"- {prefix}: id={acc.id} number={_fmt(getattr(acc, 'account_number', None))} name={_fmt(getattr(acc, 'name', None))}"
        + (f" created_at={created_at_str}" if created_at_str else '')
    )


def _print_safebox(prefix: str, sb: Optional[SafeBox]):
    if not sb:
        print(f"- {prefix}: (لا يوجد)")
        return
    created_at = getattr(sb, 'created_at', None)
    created_at_str = created_at.isoformat() if created_at else ''
    print(
        f"- {prefix}: id={sb.id} type={_fmt(getattr(sb, 'safe_type', None))} name={_fmt(getattr(sb, 'name', None))} account_id={_fmt(getattr(sb, 'account_id', None))}"
        + (f" created_at={created_at_str}" if created_at_str else '')
    )


def _candidate_accounts_for_employee_name(employee_name: str):
    name = (employee_name or '').strip()
    if not name:
        return []

    # Match common auto-generated patterns to avoid huge output.
    keywords = [
        'الموظف',
        'ذمم',
        'سلف',
        'عهدة',
        'صندوق',
    ]

    q = Account.query

    # Must contain the employee name.
    q = q.filter(Account.name.ilike(f"%{name}%"))

    # And contain one of the keywords.
    from sqlalchemy import or_

    q = q.filter(or_(*[Account.name.ilike(f"%{k}%") for k in keywords]))

    # Prefer newest first if created_at exists.
    if hasattr(Account, 'created_at'):
        q = q.order_by(Account.created_at.desc())
    else:
        q = q.order_by(Account.id.desc())

    return q.limit(100).all()


def _candidate_safeboxes_for_employee_name(employee_name: str):
    name = (employee_name or '').strip()
    if not name:
        return []

    keywords = [
        'الموظف',
        'عهدة',
        'صندوق',
    ]

    q = SafeBox.query
    q = q.filter(SafeBox.name.ilike(f"%{name}%"))

    from sqlalchemy import or_

    q = q.filter(or_(*[SafeBox.name.ilike(f"%{k}%") for k in keywords]))
    if hasattr(SafeBox, 'created_at'):
        q = q.order_by(SafeBox.created_at.desc())
    else:
        q = q.order_by(SafeBox.id.desc())

    return q.limit(100).all()


def main():
    parser = argparse.ArgumentParser(description='Trace employee creation artifacts (accounts + safes).')
    parser.add_argument('--name', help='Employee name (Arabic)')
    parser.add_argument('--code', help='Employee code (e.g., EMP-2026-0001)')
    args = parser.parse_args()

    if not args.name and not args.code:
        parser.error('Provide --name or --code')

    with app.app_context():
        emp = None
        if args.code:
            emp = Employee.query.filter_by(employee_code=args.code).first()
        if not emp and args.name:
            # If multiple matches, show all candidates.
            matches = Employee.query.filter(Employee.name.ilike(f"%{args.name.strip()}%")).order_by(Employee.id.desc()).all()
            if not matches:
                print('لم يتم العثور على موظف مطابق.')
                return 1
            if len(matches) > 1:
                print('وجدت أكثر من موظف مطابق، سأعرضهم جميعاً (الأحدث أولاً):')
                for m in matches[:20]:
                    print(f"- id={m.id} code={_fmt(m.employee_code)} name={_fmt(m.name)}")
                emp = matches[0]
                print(f"\nسأستخدم الأحدث: id={emp.id} ({_fmt(emp.employee_code)})")
            else:
                emp = matches[0]

        if not emp:
            print('لم يتم العثور على موظف مطابق.')
            return 1

        print('=== Employee ===')
        print(f"- id={emp.id}")
        print(f"- code={_fmt(getattr(emp, 'employee_code', None))}")
        print(f"- name={_fmt(getattr(emp, 'name', None))}")
        print(f"- account_id={_fmt(getattr(emp, 'account_id', None))}")
        print(f"- cash_safe_box_id={_fmt(getattr(emp, 'cash_safe_box_id', None))}")
        print(f"- gold_safe_box_id={_fmt(getattr(emp, 'gold_safe_box_id', None))}")

        print('\n=== Linked Accounts ===')
        personal_acc = Account.query.get(emp.account_id) if getattr(emp, 'account_id', None) else None
        _print_account('Personal account', personal_acc)

        print('\n=== Linked Safes ===')
        cash_sb = SafeBox.query.get(getattr(emp, 'cash_safe_box_id', None)) if getattr(emp, 'cash_safe_box_id', None) else None
        gold_sb = SafeBox.query.get(getattr(emp, 'gold_safe_box_id', None)) if getattr(emp, 'gold_safe_box_id', None) else None
        _print_safebox('Cash SafeBox', cash_sb)
        _print_safebox('Gold SafeBox', gold_sb)

        cash_acc = Account.query.get(getattr(cash_sb, 'account_id', None)) if cash_sb and getattr(cash_sb, 'account_id', None) else None
        gold_acc = Account.query.get(getattr(gold_sb, 'account_id', None)) if gold_sb and getattr(gold_sb, 'account_id', None) else None

        _print_account('Cash Safe account', cash_acc)
        _print_account('Gold Safe account', gold_acc)

        print('\n=== Matching Auto-Generated Accounts (by name) ===')
        accounts = _candidate_accounts_for_employee_name(getattr(emp, 'name', '') or args.name or '')
        if not accounts:
            print('- (لا يوجد)')
        else:
            for acc in accounts:
                _print_account('Account', acc)

        print('\n=== Matching SafeBoxes (by name) ===')
        safes = _candidate_safeboxes_for_employee_name(getattr(emp, 'name', '') or args.name or '')
        if not safes:
            print('- (لا يوجد)')
        else:
            for sb in safes:
                _print_safebox('SafeBox', sb)
                linked = Account.query.get(getattr(sb, 'account_id', None)) if getattr(sb, 'account_id', None) else None
                _print_account('  linked account', linked)

        return 0


if __name__ == '__main__':
    raise SystemExit(main())
