#!/usr/bin/env python3
"""Delete an invoice and rebuild stored balances.

This is an operational repair tool.

Typical use-case:
- You accidentally imported/created a duplicate invoice.
- You want to remove the duplicate invoice (and its accounting artifacts)
  then rebuild stored balances to ensure consistency.

By default this script is DRY-RUN.

Usage:
  ./venv/bin/python devtools/delete_invoice_and_rebuild_balances.py --invoice-id 26
  ./venv/bin/python devtools/delete_invoice_and_rebuild_balances.py --invoice-id 26 --apply

Notes:
- Deletes related JournalEntries (reference_type='invoice', reference_id=invoice_id)
- Deletes related Vouchers (reference_type='invoice', reference_id=invoice_id)
- Deletes related SafeBoxTransactions (invoice_id=..., invoice_payment_id in payments)
- Rebuilds stored Account balances (journal + vouchers)
- Rebuilds stored Customer balances (journal lines with customer_id)

If you are unsure, run dry-run first.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Iterable

# Ensure the backend package root is importable when running from backend/devtools.
_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from app import app
from models import (
    Customer,
    Invoice,
    InvoiceItem,
    InvoiceKaratLine,
    InvoicePayment,
    InvoiceWeightSettlement,
    JournalEntry,
    JournalEntryLine,
    SafeBoxTransaction,
    Voucher,
    VoucherAccountLine,
    db,
)


def _bool_col_exists(model, col: str) -> bool:
    try:
        return hasattr(model, col)
    except Exception:
        return False


def _iter_int(values: Iterable[int | str]) -> list[int]:
    out: list[int] = []
    for v in values:
        try:
            out.append(int(v))
        except Exception:
            continue
    return out


def _rebuild_customer_balances() -> dict:
    # Reset
    db.session.query(Customer).update(
        {
            Customer.balance_cash: 0.0,
            Customer.balance_gold_18k: 0.0,
            Customer.balance_gold_21k: 0.0,
            Customer.balance_gold_22k: 0.0,
            Customer.balance_gold_24k: 0.0,
        },
        synchronize_session=False,
    )

    # Aggregate deltas from posted, non-deleted journal lines.
    filters = [
        JournalEntry.is_deleted == False,
        JournalEntryLine.is_deleted == False,
        JournalEntryLine.customer_id.isnot(None),
    ]

    if _bool_col_exists(JournalEntry, 'is_posted'):
        filters.append(JournalEntry.is_posted == True)
    elif _bool_col_exists(JournalEntry, 'is_draft'):
        filters.append(JournalEntry.is_draft == False)

    rows = (
        db.session.query(
            JournalEntryLine.customer_id.label('customer_id'),
            (db.func.coalesce(db.func.sum(JournalEntryLine.cash_debit), 0.0) - db.func.coalesce(db.func.sum(JournalEntryLine.cash_credit), 0.0)).label('cash'),
            (db.func.coalesce(db.func.sum(JournalEntryLine.debit_18k), 0.0) - db.func.coalesce(db.func.sum(JournalEntryLine.credit_18k), 0.0)).label('b18'),
            (db.func.coalesce(db.func.sum(JournalEntryLine.debit_21k), 0.0) - db.func.coalesce(db.func.sum(JournalEntryLine.credit_21k), 0.0)).label('b21'),
            (db.func.coalesce(db.func.sum(JournalEntryLine.debit_22k), 0.0) - db.func.coalesce(db.func.sum(JournalEntryLine.credit_22k), 0.0)).label('b22'),
            (db.func.coalesce(db.func.sum(JournalEntryLine.debit_24k), 0.0) - db.func.coalesce(db.func.sum(JournalEntryLine.credit_24k), 0.0)).label('b24'),
        )
        .join(JournalEntry)
        .filter(*filters)
        .group_by(JournalEntryLine.customer_id)
        .all()
    )

    updates: list[dict] = []
    for r in rows:
        if r.customer_id is None:
            continue
        updates.append(
            {
                'id': int(r.customer_id),
                'balance_cash': float(r.cash or 0.0),
                'balance_gold_18k': float(r.b18 or 0.0),
                'balance_gold_21k': float(r.b21 or 0.0),
                'balance_gold_22k': float(r.b22 or 0.0),
                'balance_gold_24k': float(r.b24 or 0.0),
            }
        )

    if updates:
        db.session.bulk_update_mappings(Customer, updates)

    db.session.commit()

    return {
        'updated_customers': len(updates),
        'journal_customers': len(rows),
    }


def _rebuild_account_balances() -> dict:
    # Reuse the backend implementation.
    import routes  # local import to avoid heavy load if not needed

    stats = routes._rebuild_all_account_balances()  # pylint: disable=protected-access
    return stats


def _collect_related(invoice_id: int) -> dict:
    invoice = Invoice.query.get(invoice_id)
    if not invoice:
        raise ValueError(f"Invoice #{invoice_id} not found")

    payment_ids = _iter_int([p.id for p in (invoice.payments or [])])

    jes = (
        JournalEntry.query.filter(JournalEntry.reference_type == 'invoice')
        .filter(JournalEntry.reference_id == invoice_id)
        .all()
    )
    je_ids = _iter_int([je.id for je in jes])

    vouchers = (
        Voucher.query.filter(Voucher.reference_type == 'invoice')
        .filter(Voucher.reference_id == invoice_id)
        .all()
    )
    voucher_ids = _iter_int([v.id for v in vouchers])

    voucher_je_ids = _iter_int([v.journal_entry_id for v in vouchers if v.journal_entry_id])

    safe_tx = list(SafeBoxTransaction.query.filter(SafeBoxTransaction.invoice_id == invoice_id).all())
    if payment_ids:
        safe_tx2 = list(
            SafeBoxTransaction.query.filter(SafeBoxTransaction.invoice_payment_id.in_(payment_ids)).all()
        )
        seen = {t.id for t in safe_tx}
        for t in safe_tx2:
            if t.id not in seen:
                safe_tx.append(t)
                seen.add(t.id)

    safe_tx_ids = _iter_int([t.id for t in safe_tx])

    return {
        'invoice': invoice,
        'payment_ids': payment_ids,
        'je_ids': sorted(set(je_ids)),
        'voucher_ids': sorted(set(voucher_ids)),
        'voucher_je_ids': sorted(set(voucher_je_ids)),
        'safe_tx_ids': sorted(set(safe_tx_ids)),
    }


def _dry_run_report(related: dict) -> None:
    invoice: Invoice = related['invoice']
    print('DRY-RUN: no data will be modified')
    print(f"Invoice: #{invoice.id} type={invoice.invoice_type} date={invoice.date} total={invoice.total} posted={bool(invoice.is_posted)}")
    print(f"  items: {len(invoice.items or [])}")
    print(f"  payments: {len(invoice.payments or [])} (ids={related['payment_ids']})")
    print(f"  journal_entries (invoice ref): {len(related['je_ids'])} ids={related['je_ids']}")
    print(f"  vouchers (invoice ref): {len(related['voucher_ids'])} ids={related['voucher_ids']}")
    print(f"  journal_entries (via vouchers): {len(related['voucher_je_ids'])} ids={related['voucher_je_ids']}")
    print(f"  safe_box_transactions: {len(related['safe_tx_ids'])} ids={related['safe_tx_ids']}")


def _apply_delete(related: dict) -> None:
    invoice: Invoice = related['invoice']

    payment_ids: list[int] = related['payment_ids']
    je_ids: list[int] = related['je_ids']
    voucher_ids: list[int] = related['voucher_ids']
    voucher_je_ids: list[int] = related['voucher_je_ids']
    safe_tx_ids: list[int] = related['safe_tx_ids']

    all_je_ids = sorted(set(je_ids + voucher_je_ids))

    # 1) SafeBox ledger
    if safe_tx_ids:
        db.session.query(SafeBoxTransaction).filter(SafeBoxTransaction.id.in_(safe_tx_ids)).delete(
            synchronize_session=False
        )

    # 2) Vouchers
    if voucher_ids:
        db.session.query(VoucherAccountLine).filter(VoucherAccountLine.voucher_id.in_(voucher_ids)).delete(
            synchronize_session=False
        )
        db.session.query(Voucher).filter(Voucher.id.in_(voucher_ids)).delete(synchronize_session=False)

    # 3) Journal entries
    if all_je_ids:
        db.session.query(JournalEntryLine).filter(JournalEntryLine.journal_entry_id.in_(all_je_ids)).delete(
            synchronize_session=False
        )
        db.session.query(JournalEntry).filter(JournalEntry.id.in_(all_je_ids)).delete(synchronize_session=False)

    # 4) Invoice children
    if payment_ids:
        db.session.query(InvoicePayment).filter(InvoicePayment.id.in_(payment_ids)).delete(synchronize_session=False)

    db.session.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice.id).delete(synchronize_session=False)
    db.session.query(InvoiceKaratLine).filter(InvoiceKaratLine.invoice_id == invoice.id).delete(
        synchronize_session=False
    )
    db.session.query(InvoiceWeightSettlement).filter(InvoiceWeightSettlement.invoice_id == invoice.id).delete(
        synchronize_session=False
    )

    # 5) Invoice
    db.session.query(Invoice).filter(Invoice.id == invoice.id).delete(synchronize_session=False)

    db.session.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description='Delete invoice and rebuild balances')
    parser.add_argument('--invoice-id', type=int, required=True)
    parser.add_argument('--apply', action='store_true', help='Actually delete and rebuild (otherwise dry-run)')
    parser.add_argument('--no-rebuild-accounts', action='store_true', help='Skip rebuilding Account balances')
    parser.add_argument('--no-rebuild-customers', action='store_true', help='Skip rebuilding Customer balances')
    args = parser.parse_args()

    with app.app_context():
        related = _collect_related(args.invoice_id)

        if not args.apply:
            _dry_run_report(related)
            return 0

        print(f"Deleting invoice #{args.invoice_id} and related artifacts...")
        _apply_delete(related)

        if not bool(args.no_rebuild_accounts):
            print('Rebuilding account balances...')
            stats = _rebuild_account_balances()
            print(f"  account stats: {stats}")

        if not bool(args.no_rebuild_customers):
            print('Rebuilding customer balances...')
            stats = _rebuild_customer_balances()
            print(f"  customer stats: {stats}")

        print('Done.')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
