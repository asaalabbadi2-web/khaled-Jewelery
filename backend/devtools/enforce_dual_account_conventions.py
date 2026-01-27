#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Enforce dual-chart conventions for accounts (financial vs memo).

Conventions:
- Memo (weight) accounts: account_number starts with '7'
  - transaction_type = 'gold'
  - tracks_weight = True
- Financial accounts: everything else
  - transaction_type = 'cash'
  - tracks_weight = False

Linking:
- Financial -> Memo via memo_account_id should point to memo_number='7'+financial.account_number.
- Memo -> Financial may store a reverse link in memo.memo_account_id.

Safety:
- Default is DRY RUN (no DB writes).
- Use --apply to commit changes.
- By default, this script will NOT create missing counterpart accounts.
  - Use --create-missing-memo to create missing memo accounts for financial accounts.
  - Use --create-missing-financial to create missing financial accounts for memo accounts.

Usage:
  cd backend
  BYPASS_AUTH_FOR_DEVELOPMENT=1 ./venv/bin/python devtools/enforce_dual_account_conventions.py

  BYPASS_AUTH_FOR_DEVELOPMENT=1 ./venv/bin/python devtools/enforce_dual_account_conventions.py --apply

  BYPASS_AUTH_FOR_DEVELOPMENT=1 ./venv/bin/python devtools/enforce_dual_account_conventions.py \
    --create-missing-memo --apply
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault('BYPASS_AUTH_FOR_DEVELOPMENT', '1')

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app import app  # noqa: E402
from models import Account, db  # noqa: E402
from config import WEIGHT_SUPPORT_ACCOUNTS  # noqa: E402


def _digits_only(value: str) -> str:
    return ''.join(ch for ch in str(value or '').strip() if ch.isdigit())


def _is_memo_number(account_number: str) -> bool:
    return (account_number or '').strip().startswith('7')


def _memo_number_from_financial(financial_number: str) -> str:
    digits = _digits_only(financial_number)
    if not digits:
        raise ValueError('Invalid financial account number')
    return f"7{digits}"


def _financial_number_from_memo(memo_number: str) -> str:
    digits = _digits_only(memo_number)
    if not digits or not digits.startswith('7') or len(digits) <= 1:
        raise ValueError('Invalid memo account number')
    return digits[1:]


def main(argv: list[str]) -> int:
    apply = '--apply' in argv
    create_missing_memo = '--create-missing-memo' in argv
    create_missing_financial = '--create-missing-financial' in argv

    with app.app_context():
        accounts = Account.query.order_by(Account.account_number.asc()).all()

        planned_field_updates: list[tuple[Account, str, object, object]] = []
        planned_links: list[str] = []
        planned_creates: list[str] = []

        def set_if_diff(acc: Account, field: str, desired: object) -> None:
            current = getattr(acc, field)
            if current != desired:
                planned_field_updates.append((acc, field, current, desired))
                setattr(acc, field, desired)

        by_number: dict[str, Account] = {
            _digits_only(a.account_number): a for a in accounts if _digits_only(a.account_number)
        }

        # 1) Normalize per-prefix rules.
        for acc in accounts:
            n = _digits_only(acc.account_number)
            if not n:
                continue
            if _is_memo_number(n):
                set_if_diff(acc, 'transaction_type', 'gold')
                set_if_diff(acc, 'tracks_weight', True)
            else:
                set_if_diff(acc, 'transaction_type', 'cash')
                set_if_diff(acc, 'tracks_weight', False)

        # Build explicit mapping for special support accounts.
        explicit_fin_to_memo: dict[str, str] = {}
        explicit_memo_to_fin: dict[str, str] = {}
        try:
            for entry in WEIGHT_SUPPORT_ACCOUNTS:
                fin_no = _digits_only((entry.get('financial') or {}).get('account_number'))
                memo_no = _digits_only((entry.get('memo') or {}).get('account_number'))
                if fin_no and memo_no:
                    explicit_fin_to_memo[fin_no] = memo_no
                    explicit_memo_to_fin[memo_no] = fin_no
        except Exception:
            explicit_fin_to_memo = {}
            explicit_memo_to_fin = {}

        # 2) Ensure linking consistency.
        # Financial: memo_account_id should point to either the explicit support memo (if defined)
        # or the generic memo number (7 + financial).
        for acc in accounts:
            n = _digits_only(acc.account_number)
            if not n or _is_memo_number(n):
                continue

            if n in explicit_fin_to_memo:
                memo_number = explicit_fin_to_memo[n]
            else:
                memo_number = _memo_number_from_financial(n)
            memo = by_number.get(_digits_only(memo_number))

            if memo is None and create_missing_memo:
                memo = Account(
                    account_number=_digits_only(memo_number),
                    name=f"{acc.name} وزني",
                    type=acc.type,
                    transaction_type='gold',
                    tracks_weight=True,
                )
                db.session.add(memo)
                db.session.flush()
                by_number[_digits_only(memo_number)] = memo
                planned_creates.append(f"create memo {memo.account_number} for financial {acc.account_number}")

            if memo is None:
                continue

            # Fix memo semantics if it exists.
            set_if_diff(memo, 'transaction_type', 'gold')
            set_if_diff(memo, 'tracks_weight', True)

            if acc.memo_account_id != memo.id:
                planned_links.append(
                    f"link financial {acc.account_number} memo_account_id {acc.memo_account_id} -> {memo.id}"
                )
                acc.memo_account_id = memo.id

            if memo.memo_account_id != acc.id:
                planned_links.append(
                    f"link memo {memo.account_number} memo_account_id {memo.memo_account_id} -> {acc.id}"
                )
                memo.memo_account_id = acc.id

        # Memo: ensure reverse link points to stripped financial number (create optionally).
        for acc in accounts:
            n = _digits_only(acc.account_number)
            if not n or not _is_memo_number(n) or len(n) <= 1:
                continue

            if n in explicit_memo_to_fin:
                fin_number = explicit_memo_to_fin[n]
            else:
                try:
                    fin_number = _financial_number_from_memo(n)
                except Exception:
                    continue

                # If the derived financial number has an explicit memo mapping,
                # do not allow a different generic memo (e.g. 71300) to claim it
                # when the system expects a special support memo (e.g. 7130000).
                if fin_number in explicit_fin_to_memo and explicit_fin_to_memo[fin_number] != n:
                    continue

            fin = by_number.get(_digits_only(fin_number))
            if fin is None and create_missing_financial:
                fin = Account(
                    account_number=_digits_only(fin_number),
                    name=acc.name.replace(' وزني', '').strip() or acc.name,
                    type=acc.type,
                    transaction_type='cash',
                    tracks_weight=False,
                )
                db.session.add(fin)
                db.session.flush()
                by_number[_digits_only(fin_number)] = fin
                planned_creates.append(f"create financial {fin.account_number} for memo {acc.account_number}")

            if fin is None:
                continue

            set_if_diff(fin, 'transaction_type', 'cash')
            set_if_diff(fin, 'tracks_weight', False)

            if fin.memo_account_id != acc.id:
                planned_links.append(
                    f"link financial {fin.account_number} memo_account_id {fin.memo_account_id} -> {acc.id}"
                )
                fin.memo_account_id = acc.id

            if acc.memo_account_id != fin.id:
                planned_links.append(
                    f"link memo {acc.account_number} memo_account_id {acc.memo_account_id} -> {fin.id}"
                )
                acc.memo_account_id = fin.id

        print(f"Total accounts: {len(accounts)}")
        print(f"Planned field updates: {len(planned_field_updates)}")
        print(f"Planned link updates: {len(planned_links)}")
        print(f"Planned creates: {len(planned_creates)}")

        for line in planned_creates[:20]:
            print(f"- {line}")
        for line in planned_links[:20]:
            print(f"- {line}")
        for acc, field, cur, des in planned_field_updates[:25]:
            print(f"- {acc.account_number} {field}: {cur} -> {des} ({acc.name})")

        if not apply:
            print('DRY RUN: no changes applied. Re-run with --apply to commit.')
            db.session.rollback()
            return 0

        changed = bool(planned_field_updates or planned_links or planned_creates)
        if changed:
            db.session.commit()
        print('Applied changes.' if changed else 'No changes needed.')
        return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
