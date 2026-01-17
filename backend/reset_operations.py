#!/usr/bin/env python3
"""Utility helpers to wipe operational data and restart testing from a clean slate.

Run from the backend folder after activating the virtual environment:

    python reset_operations.py --yes

Optional flags let you clear master data (customers/suppliers/items) or gold price
snapshots as well.

Note: The admin dashboard derives cash/gold balances from SafeBoxTransaction.
If you deleted invoices/journals but still see balances, use --purge-ledger.
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
    AuditLog,
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
    SafeBoxTransaction,
    Supplier,
    SupplierGoldTransaction,
    SystemAlert,
    Voucher,
    VoucherAccountLine,
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


def _reset_customers() -> int:
    customers = Customer.query.all()
    for customer in customers:
        # Keep master record; just zero cached balances.
        if hasattr(customer, 'balance_cash'):
            customer.balance_cash = 0.0
        if hasattr(customer, 'balance_gold_18k'):
            customer.balance_gold_18k = 0.0
        if hasattr(customer, 'balance_gold_21k'):
            customer.balance_gold_21k = 0.0
        if hasattr(customer, 'balance_gold_22k'):
            customer.balance_gold_22k = 0.0
        if hasattr(customer, 'balance_gold_24k'):
            customer.balance_gold_24k = 0.0
    return len(customers)


def reset_operations(
    *,
    purge_master: bool = False,
    purge_prices: bool = False,
    purge_ledger: bool = False,
    purge_alerts: bool = False,
    purge_audit: bool = False,
    purge_vouchers: bool = False,
) -> Dict[str, int]:
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

    if purge_vouchers:
        # Vouchers can have their own posting/ledger side effects.
        stats['voucher_account_lines'] = _bulk_delete(VoucherAccountLine)
        stats['vouchers'] = _bulk_delete(Voucher)

    if purge_ledger:
        # SafeBoxTransaction is the source of truth for cash/gold balances.
        stats['safe_box_transactions'] = _bulk_delete(SafeBoxTransaction)

    if purge_alerts:
        stats['system_alerts'] = _bulk_delete(SystemAlert)

    if purge_audit:
        stats['audit_logs'] = _bulk_delete(AuditLog)

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
    stats['customers_reset'] = _reset_customers()
    db.session.commit()
    return stats


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Reset operational data (invoices, journals, costing, etc.).')
    parser.add_argument(
        '--nuclear',
        action='store_true',
        help=(
            'Nuclear reset (testing only): deletes SafeBoxTransaction, invoices, journals, '
            'system alerts, audit logs, vouchers, and closing logs; keeps master structure '
            '(safe boxes, branches, employees, chart of accounts).' 
            'Equivalent to: --purge-ledger --purge-vouchers --purge-alerts --purge-audit'
        ),
    )
    parser.add_argument('--purge-master', action='store_true', help='Delete customers, suppliers, and items as well.')
    parser.add_argument('--purge-prices', action='store_true', help='Delete cached gold price history.')
    parser.add_argument('--purge-ledger', action='store_true', help='Delete safebox ledger transactions (resets dashboard balances).')
    parser.add_argument('--purge-alerts', action='store_true', help='Delete system alerts.')
    parser.add_argument('--purge-audit', action='store_true', help='Delete audit logs.')
    parser.add_argument('--purge-vouchers', action='store_true', help='Delete vouchers and their lines.')
    parser.add_argument('--yes', action='store_true', help='Skip the safety prompt.')
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if args.nuclear:
        # Expand nuclear reset into explicit flags.
        args.purge_ledger = True
        args.purge_vouchers = True
        args.purge_alerts = True
        args.purge_audit = True

    if not args.yes:
        if args.nuclear:
            print('☢️  NUCLEAR RESET (testing only): this deletes ledger, invoices, journals, alerts, audit, vouchers.')
        else:
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
            purge_ledger=args.purge_ledger,
            purge_alerts=args.purge_alerts,
            purge_audit=args.purge_audit,
            purge_vouchers=args.purge_vouchers,
        )
        elapsed = (datetime.utcnow() - started).total_seconds()

    print('\n✅ Operations reset complete:')
    for label, count in stats.items():
        print(f'  - {label}: {count}')
    print(f'⏱️  Took {elapsed:.2f}s')


if __name__ == '__main__':
    main()
