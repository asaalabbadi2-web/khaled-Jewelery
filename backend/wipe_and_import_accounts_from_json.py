#!/usr/bin/env python3
"""Wipe and import chart of accounts from a previously-exported JSON file.

This is intentionally *destructive*.

Supported JSON formats:
1) API export format (recommended):
   {
     "version": 1,
     "exported_at": "...",
     "count": N,
     "accounts": [
        {
          "account_number": "111",
          "name": "الصندوق",
          "type": "Asset",
          "transaction_type": "cash",
          "tracks_weight": false,
          "parent_account_number": "11",
          "memo_account_number": "1W11",
          ...
        }
     ]
   }

2) Legacy import dict (like exports/accounts_import.json):
   {
     "1100": {
       "account_number": "1100",
       "name": "الصندوق",
       "type": "Asset",
       "tracks_weight": 0,
       "parent_account_number": "110",
       "memo_account_number": "71100"
     },
     ...
   }

3) Legacy export list (like exports/accounts_export.json):
   [
     {
       "id": 4,
       "account_number": "1100",
       "name": "الصندوق",
       "parent_id": 3,
       "type": "Asset",
       "tracks_weight": 0,
       "memo_account_id": 37
     },
     ...
   ]

Usage:
  python wipe_and_import_accounts_from_json.py --file ../exports/accounts_import.json --wipe --yes

Notes:
- Wiping accounts requires clearing or deleting dependent rows that reference account.id.
- This script will delete: journal entry lines + entries, vouchers + voucher lines,
  safe boxes, accounting mappings. It will also null out account references on
  customers/suppliers/offices/employees/invoices to avoid FK issues.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from app import app, db
from models import (
    Account,
    AccountingMapping,
    Customer,
    Employee,
    Invoice,
    JournalEntry,
    JournalEntryLine,
    Office,
    PaymentMethod,
    SafeBox,
    SafeBoxTransaction,
    Settings,
    Supplier,
    Voucher,
    VoucherAccountLine,
)

# Recurring journal tables live outside models.py but still reference account.id
from recurring_journal_system import RecurringJournalLine, RecurringJournalTemplate


def _derive_transaction_type(account_number: str, tracks_weight: bool) -> str:
    n = (account_number or '').strip()
    if n.startswith(('1W', '2W', '3W', '4W', '5W')):
        return 'gold'
    # Legacy memo tree commonly used 7xxxx
    if n.startswith('7') and tracks_weight:
        return 'gold'
    return 'cash'


def _load_accounts_rows(file_path: Path) -> List[Dict[str, Any]]:
    raw = json.loads(file_path.read_text(encoding='utf-8'))

    # Format 1: API export dict with "accounts"
    if isinstance(raw, dict) and isinstance(raw.get('accounts'), list):
        return list(raw['accounts'])

    # Format 2: legacy dict keyed by account_number
    if isinstance(raw, dict):
        # Some exports may nest under "data"
        if isinstance(raw.get('data'), list):
            return list(raw['data'])
        if all(isinstance(v, dict) for v in raw.values()):
            return [dict(v) for v in raw.values()]

    # Format 3: legacy list
    if isinstance(raw, list):
        return [dict(v) for v in raw]

    raise ValueError('Unsupported JSON format for accounts')


def _normalize_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # If rows contain legacy ids, convert parent_id/memo_account_id -> *_account_number
    has_legacy_ids = any('id' in r and ('parent_id' in r or 'memo_account_id' in r) for r in rows)
    if has_legacy_ids:
        id_to_number: Dict[int, str] = {}
        for r in rows:
            rid = r.get('id')
            num = r.get('account_number')
            if isinstance(rid, int) and num is not None:
                id_to_number[rid] = str(num)

        normalized: List[Dict[str, Any]] = []
        for r in rows:
            account_number = str(r.get('account_number') or '').strip()
            name = str(r.get('name') or '').strip()
            acc_type = str(r.get('type') or '').strip()
            tracks_weight = bool(r.get('tracks_weight') in (1, True, '1', 'true', 'True'))

            parent_num = None
            if r.get('parent_id') is not None:
                try:
                    parent_num = id_to_number.get(int(r.get('parent_id')))
                except Exception:
                    parent_num = None

            memo_num = None
            if r.get('memo_account_id') is not None:
                try:
                    memo_num = id_to_number.get(int(r.get('memo_account_id')))
                except Exception:
                    memo_num = None

            transaction_type = (r.get('transaction_type') or '').strip() if isinstance(r.get('transaction_type'), str) else None
            if not transaction_type:
                transaction_type = _derive_transaction_type(account_number, tracks_weight)

            normalized.append({
                'account_number': account_number,
                'name': name,
                'type': acc_type,
                'transaction_type': transaction_type,
                'tracks_weight': tracks_weight,
                'bank_name': r.get('bank_name'),
                'account_number_external': r.get('account_number_external'),
                'account_type': r.get('account_type'),
                'parent_account_number': parent_num,
                'memo_account_number': memo_num,
            })
        rows = normalized

    normalized2: List[Dict[str, Any]] = []
    for r in rows:
        account_number = str(r.get('account_number') or '').strip()
        if not account_number:
            continue

        name = str(r.get('name') or '').strip()
        acc_type = str(r.get('type') or '').strip()
        tracks_weight = bool(r.get('tracks_weight', False) in (1, True, '1', 'true', 'True'))

        transaction_type = r.get('transaction_type')
        if not isinstance(transaction_type, str) or not transaction_type.strip():
            transaction_type = _derive_transaction_type(account_number, tracks_weight)
        transaction_type = transaction_type.strip()

        normalized2.append({
            'account_number': account_number,
            'name': name,
            'type': acc_type,
            'transaction_type': transaction_type,
            'tracks_weight': tracks_weight,
            'bank_name': r.get('bank_name'),
            'account_number_external': r.get('account_number_external'),
            'account_type': r.get('account_type'),
            'parent_account_number': (str(r.get('parent_account_number')).strip() if r.get('parent_account_number') is not None else None),
            'memo_account_number': (str(r.get('memo_account_number')).strip() if r.get('memo_account_number') is not None else None),
        })

    # Validate: referenced parents/memos exist in payload
    present = {r['account_number'] for r in normalized2}
    missing_refs = []
    for r in normalized2:
        p = r.get('parent_account_number')
        m = r.get('memo_account_number')
        if p and p not in present:
            missing_refs.append((r['account_number'], 'parent_account_number', p))
        if m and m not in present:
            missing_refs.append((r['account_number'], 'memo_account_number', m))

    if missing_refs:
        details = '\n'.join([f'- {a} missing {k}={v}' for a, k, v in missing_refs[:50]])
        raise ValueError(f'Missing references in import payload (showing up to 50):\n{details}')

    # Sort so parents are likely created earlier (not required but nice)
    normalized2.sort(key=lambda x: (len(x['account_number']), x['account_number']))
    return normalized2


def _wipe_dependent_rows() -> None:
    # Null FK references to accounts/safe boxes where possible
    # Settings does not have safe-box FK; PaymentMethod does.
    PaymentMethod.query.update({PaymentMethod.default_safe_box_id: None})

    Invoice.query.update({Invoice.safe_box_id: None, Invoice.wage_inventory_account_id: None})
    Office.query.update({Office.account_category_id: None})
    Supplier.query.update({Supplier.account_category_id: None, Supplier.account_id: None})
    Customer.query.update({Customer.account_category_id: None, Customer.account_id: None})
    Employee.query.update({Employee.account_id: None})

    # Recurring journal templates/lines reference accounts and must be cleared
    RecurringJournalLine.query.delete()
    RecurringJournalTemplate.query.delete()

    # Delete tables that require account_id (NOT NULL) or safe_box account dependency
    VoucherAccountLine.query.delete()
    Voucher.query.delete()

    JournalEntryLine.query.delete()
    JournalEntry.query.delete()

    AccountingMapping.query.delete()

    # SafeBoxTransaction.safe_box_id is NOT NULL; delete explicitly before safe boxes.
    SafeBoxTransaction.query.delete()
    SafeBox.query.delete()


def _import_accounts(rows: List[Dict[str, Any]]) -> int:
    created = 0

    # Pass 1: create core accounts
    by_number: Dict[str, Account] = {}
    for r in rows:
        acc = Account(
            account_number=r['account_number'],
            name=r['name'],
            type=r['type'],
            transaction_type=r['transaction_type'],
            tracks_weight=bool(r['tracks_weight']),
        )
        acc.bank_name = r.get('bank_name')
        acc.account_number_external = r.get('account_number_external')
        acc.account_type = r.get('account_type')

        db.session.add(acc)
        by_number[r['account_number']] = acc
        created += 1

    db.session.flush()

    number_to_id = {n: a.id for n, a in by_number.items()}

    # Pass 2: set relationships
    for r in rows:
        acc = by_number[r['account_number']]
        parent_num = r.get('parent_account_number')
        memo_num = r.get('memo_account_number')
        acc.parent_id = number_to_id.get(parent_num) if parent_num else None
        acc.memo_account_id = number_to_id.get(memo_num) if memo_num else None
        db.session.add(acc)

    db.session.commit()
    return created


def main() -> int:
    parser = argparse.ArgumentParser(description='Wipe all accounts and import from JSON')
    parser.add_argument('--file', required=True, help='Path to JSON file (export/import)')
    parser.add_argument('--dry-run', action='store_true', help='Preview parsed data without modifying the database')
    parser.add_argument('--wipe', action='store_true', help='Actually wipe all accounts before import')
    parser.add_argument('--yes', action='store_true', help='Confirm destructive wipe (required with --wipe)')
    args = parser.parse_args()

    file_path = Path(args.file).expanduser().resolve()
    if not file_path.exists():
        raise SystemExit(f'File not found: {file_path}')

    with app.app_context():
        print('=' * 60)
        print('🧾 Accounts JSON import')
        print('=' * 60)
        print(f'Using file: {file_path}')

        rows_raw = _load_accounts_rows(file_path)
        rows = _normalize_rows(rows_raw)
        print(f'Parsed accounts rows: {len(rows)}')

        gold_like = [r for r in rows if str(r.get('account_number', '')).startswith(('1W', '2W', '3W', '4W', '5W'))]
        legacy_memo_like = [r for r in rows if str(r.get('account_number', '')).startswith('7')]
        print(f"Detected gold-style accounts (1W..5W): {len(gold_like)}")
        print(f"Detected legacy memo-tree accounts (7xxxx): {len(legacy_memo_like)}")

        if args.dry_run:
            print('✅ Dry-run complete (no database changes).')
            return 0

        if args.wipe:
            if not args.yes:
                raise SystemExit('Refusing to wipe without --yes')

            print('⚠️  WIPING dependent accounting data + all accounts...')
            _wipe_dependent_rows()
            Account.query.delete()
            db.session.commit()
            print('✅ Wipe completed.')
        else:
            raise SystemExit('This script only supports full replace. Re-run with --wipe --yes')

        print('⬆️  Importing accounts...')
        created = _import_accounts(rows)
        print(f'✅ Imported accounts: {created}')

        # Refresh in-memory cache (best-effort)
        try:
            from refresh_account_cache import refresh_account_cache

            cache_size = refresh_account_cache()
            print(f'✅ Refreshed account cache: {cache_size}')
        except Exception as e:
            print(f'⚠️  Cache refresh skipped/failed: {e}')

        return 0


if __name__ == '__main__':
    raise SystemExit(main())
