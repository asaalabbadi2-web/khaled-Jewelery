#!/usr/bin/env python3
"""Utility helpers to wipe operational data and restart testing from a clean slate.

Run from the backend folder after activating the virtual environment:

    python reset_operations.py --yes

Optional flags let you clear master data (customers/suppliers/items) or gold price
snapshots as well.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import Dict

from app import app, db
from gold_costing_service import GoldCostingService
from models import (
    Account,
    Customer,
    GoldPrice,
    InventoryCostingConfig,
    Invoice,
    InvoiceItem,
    InvoiceKaratLine,
    InvoicePayment,
    Item,
    JournalEntry,
    JournalEntryLine,
    Supplier,
    SupplierGoldTransaction,
    WeightClosingLog,
)


def _bulk_delete(model) -> int:
    """Delete all rows for the given model, returning affected count."""
    return db.session.query(model).delete(synchronize_session=False)


def _reset_accounts() -> int:
    accounts = Account.query.all()
    for account in accounts:
        account.balance_cash = 0.0
        account.balance_18k = 0.0
        account.balance_21k = 0.0
        account.balance_22k = 0.0
        account.balance_24k = 0.0
    return len(accounts)


def reset_operations(*, purge_master: bool = False, purge_prices: bool = False) -> Dict[str, int]:
    """Remove transactional data and zero snapshots so testing can start fresh."""
    stats: Dict[str, int] = {}

    stats['weight_closing_logs'] = _bulk_delete(WeightClosingLog)
    stats['invoice_payments'] = _bulk_delete(InvoicePayment)
    stats['invoice_karat_lines'] = _bulk_delete(InvoiceKaratLine)
    stats['invoice_items'] = _bulk_delete(InvoiceItem)
    stats['supplier_gold_transactions'] = _bulk_delete(SupplierGoldTransaction)
    stats['journal_entry_lines'] = _bulk_delete(JournalEntryLine)
    stats['journal_entries'] = _bulk_delete(JournalEntry)
    stats['invoices'] = _bulk_delete(Invoice)

    if purge_master:
        stats['items'] = _bulk_delete(Item)
        stats['customers'] = _bulk_delete(Customer)
        stats['suppliers'] = _bulk_delete(Supplier)

    stats['inventory_costing_config'] = _bulk_delete(InventoryCostingConfig)
    db.session.flush()
    # Recreate an empty config row for future operations
    GoldCostingService._get_config()  # pylint: disable=protected-access

    if purge_prices:
        stats['gold_price_rows'] = _bulk_delete(GoldPrice)

    stats['accounts_reset'] = _reset_accounts()
    db.session.commit()
    return stats


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Reset operational data (invoices, journals, costing, etc.).')
    parser.add_argument('--purge-master', action='store_true', help='Delete customers, suppliers, and items as well.')
    parser.add_argument('--purge-prices', action='store_true', help='Delete cached gold price history.')
    parser.add_argument('--yes', action='store_true', help='Skip the safety prompt.')
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if not args.yes:
        print('⚠️  This will delete operational data (invoices, journals, costing snapshots).')
        confirmation = input("Type 'RESET' to continue: ").strip().lower()
        if confirmation != 'reset':
            print('Aborted.')
            return

    with app.app_context():
        started = datetime.utcnow()
        stats = reset_operations(
            purge_master=args.purge_master,
            purge_prices=args.purge_prices,
        )
        elapsed = (datetime.utcnow() - started).total_seconds()

    print('\n✅ Operations reset complete:')
    for label, count in stats.items():
        print(f'  - {label}: {count}')
    print(f'⏱️  Took {elapsed:.2f}s')


if __name__ == '__main__':
    main()
