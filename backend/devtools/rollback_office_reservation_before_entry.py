#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Rollback an office reservation settlement to the state *before* a given JE.

Goal (production-safe)
----------------------
Given an OfficeReservation and a "pivot" JournalEntry id (e.g. 112), return the DB
to the same *economic* state as before that JE was created.

This script supports two rollback modes:
- soft-delete (default): soft-deletes the office_reservation JournalEntries and then
  recalculates impacted Account balances to match the new journal state.
- reverse: keeps original entries, but posts reversing JournalEntries.

In both modes, it also:
- Removes WeightClosingExecution rows linked to those entries and recomputes affected orders.
- Restores OfficeReservation fields (purchase_invoice_id/status/consumption counters).
- Relinks vouchers (invoice -> office_reservation) when the settlement relink happened.
- Deletes the generated purchase invoice when it is safe (not posted, no posted JE referencing it).

Usage (inside container)
------------------------
  export BYPASS_AUTH_FOR_DEVELOPMENT=1
  python3 /app/backend/devtools/rollback_office_reservation_before_entry.py --reservation-id 4 --before-entry-id 112
  python3 /app/backend/devtools/rollback_office_reservation_before_entry.py --reservation-id 4 --before-entry-id 112 --apply

Notes
-----
- Default is DRY RUN.
- Use --apply to write.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

os.environ.setdefault("BYPASS_AUTH_FOR_DEVELOPMENT", "1")

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app import app  # noqa: E402
from dual_system_helpers import create_dual_journal_entry, verify_dual_balance  # noqa: E402
from models import (  # noqa: E402
    Account,
    Invoice,
    InvoiceItem,
    JournalEntry,
    JournalEntryLine,
    OfficeReservation,
    Supplier,
    Voucher,
    WeightClosingExecution,
    WeightClosingOrder,
    db,
)


_REV_MARK = "ROLLBACK/عكس"
_SOFT_DEL_MARK = "ROLLBACK/حذف"


def _as_float(v) -> float:
    try:
        return float(v or 0.0)
    except Exception:
        return 0.0


def _now_utc() -> datetime:
    return datetime.utcnow()


def _get_office_reservation_entries(
    reservation_id: int,
    before_entry_id: int | None,
    entry_ids: list[int] | None,
) -> list[JournalEntry]:
    q = db.session.query(JournalEntry)
    q = q.filter(JournalEntry.is_deleted == False)  # noqa: E712
    q = q.filter(JournalEntry.reference_type == "office_reservation")
    q = q.filter(JournalEntry.reference_id == int(reservation_id))
    q = q.filter(JournalEntry.is_draft == False)  # noqa: E712
    # Most environments use posting; keep defensive.
    q = q.filter(JournalEntry.is_posted == True)  # noqa: E712

    if entry_ids:
        q = q.filter(JournalEntry.id.in_([int(x) for x in entry_ids]))
    elif before_entry_id is not None:
        q = q.filter(JournalEntry.id >= int(before_entry_id))

    return q.order_by(JournalEntry.date.asc(), JournalEntry.id.asc()).all()


def _get_entry_lines(entry_id: int) -> list[JournalEntryLine]:
    return (
        db.session.query(JournalEntryLine)
        .filter(JournalEntryLine.journal_entry_id == int(entry_id))
        .filter((JournalEntryLine.is_deleted == False) | (JournalEntryLine.is_deleted.is_(None)))  # noqa: E712
        .order_by(JournalEntryLine.id.asc())
        .all()
    )


def _already_has_reversal(reservation_id: int, original_entry_number: str) -> bool:
    if not original_entry_number:
        return False
    q = db.session.query(JournalEntry)
    q = q.filter(JournalEntry.is_deleted == False)  # noqa: E712
    q = q.filter(JournalEntry.reference_type == "office_reservation")
    q = q.filter(JournalEntry.reference_id == int(reservation_id))
    q = q.filter(JournalEntry.is_posted == True)  # noqa: E712
    q = q.filter(JournalEntry.description.ilike(f"%{_REV_MARK}%"))
    q = q.filter(JournalEntry.description.ilike(f"%{original_entry_number}%"))
    return q.first() is not None


def _reverse_journal_entry(*, reservation: OfficeReservation, original: JournalEntry, posted_by: str, apply: bool) -> int | None:
    if _already_has_reversal(int(reservation.id), str(original.entry_number or "")):
        print(f"SKIP: reversal exists for JE#{original.id} {original.entry_number}")
        return None

    lines = _get_entry_lines(int(original.id))
    if not lines:
        print(f"SKIP: no lines for JE#{original.id} {original.entry_number}")
        return None

    print(f"{'APPLY' if apply else 'PLAN'}: reverse JE#{original.id} {original.entry_number} ({len(lines)} lines)")
    if not apply:
        return None

    rev = JournalEntry(
        date=original.date,
        description=(
            f"{_REV_MARK} قبل القيد #{original.id} ({original.entry_number}) - {reservation.reservation_code}"
        ),
        entry_type="عكس",
        reference_type="office_reservation",
        reference_id=int(reservation.id),
        is_posted=True,
        posted_at=original.date,
        posted_by=str(posted_by or "system"),
        created_by=str(posted_by or "system"),
    )
    db.session.add(rev)
    db.session.flush()

    for ln in lines:
        cash_debit = _as_float(getattr(ln, "cash_credit", 0.0))
        cash_credit = _as_float(getattr(ln, "cash_debit", 0.0))
        payload = {
            "cash_debit": cash_debit,
            "cash_credit": cash_credit,
            "debit_18k": _as_float(getattr(ln, "credit_18k", 0.0)),
            "credit_18k": _as_float(getattr(ln, "debit_18k", 0.0)),
            "debit_21k": _as_float(getattr(ln, "credit_21k", 0.0)),
            "credit_21k": _as_float(getattr(ln, "debit_21k", 0.0)),
            "debit_22k": _as_float(getattr(ln, "credit_22k", 0.0)),
            "credit_22k": _as_float(getattr(ln, "debit_22k", 0.0)),
            "debit_24k": _as_float(getattr(ln, "credit_24k", 0.0)),
            "credit_24k": _as_float(getattr(ln, "debit_24k", 0.0)),
        }

        has_party = bool(getattr(ln, "customer_id", None) or getattr(ln, "supplier_id", None))
        create_dual_journal_entry(
            journal_entry_id=int(rev.id),
            account_id=int(ln.account_id),
            customer_id=int(ln.customer_id) if getattr(ln, "customer_id", None) else None,
            supplier_id=int(ln.supplier_id) if getattr(ln, "supplier_id", None) else None,
            description=f"عكس: {str(getattr(ln, 'description', '') or '').strip()}",
            apply_golden_rule=False,
            exclude_from_ledger=not has_party,
            **payload,
        )

    verify_dual_balance(int(rev.id))
    return int(rev.id)


def _soft_delete_entries(entries: list[JournalEntry], *, deleted_by: str, reason: str, apply: bool) -> set[int]:
    impacted_account_ids: set[int] = set()
    for je in entries:
        lines = _get_entry_lines(int(je.id))
        for ln in lines:
            try:
                impacted_account_ids.add(int(ln.account_id))
            except Exception:
                pass

        print(f"{'APPLY' if apply else 'PLAN'}: soft-delete JE#{je.id} {je.entry_number}")
        if not apply:
            continue
        je.soft_delete(deleted_by=str(deleted_by or "system"), reason=str(reason or "rollback"))
        # Keep a searchable marker.
        try:
            if je.deletion_reason:
                je.deletion_reason = f"{_SOFT_DEL_MARK}: {je.deletion_reason}"
            else:
                je.deletion_reason = f"{_SOFT_DEL_MARK}: {reason}"
        except Exception:
            pass
        db.session.add(je)
    return impacted_account_ids


def _delete_weight_closing_executions_for_entries(entry_ids: list[int], *, apply: bool) -> set[int]:
    if not entry_ids:
        return set()

    execs = (
        db.session.query(WeightClosingExecution)
        .filter(WeightClosingExecution.journal_entry_id.in_([int(x) for x in entry_ids]))
        .all()
    )
    if not execs:
        return set()

    affected_orders: set[int] = set()
    for ex in execs:
        try:
            affected_orders.add(int(ex.order_id))
        except Exception:
            pass

    print(
        f"{'APPLY' if apply else 'PLAN'}: delete WeightClosingExecution rows count={len(execs)} for JE ids={entry_ids}"
    )

    if apply:
        for ex in execs:
            db.session.delete(ex)

    return affected_orders


def _recompute_weight_closing_order(order_id: int, *, apply: bool):
    order = db.session.query(WeightClosingOrder).filter(WeightClosingOrder.id == int(order_id)).first()
    if not order:
        return

    remaining_execs = (
        db.session.query(WeightClosingExecution)
        .filter(WeightClosingExecution.order_id == int(order.id))
        .all()
    )
    executed = sum(_as_float(getattr(ex, "weight_main_karat", 0.0)) for ex in remaining_execs)
    total = _as_float(getattr(order, "total_weight_main_karat", 0.0))
    remaining = max(total - executed, 0.0)
    if executed <= 0.000001:
        status = "open"
    elif remaining <= 0.0001:
        status = "closed"
    else:
        status = "partially_closed"

    print(
        f"{'APPLY' if apply else 'PLAN'}: recompute WCO#{order.id} executed={executed:.6f} remaining={remaining:.6f} status={status}"
    )
    if not apply:
        return

    order.executed_weight_main_karat = float(executed)
    order.remaining_weight_main_karat = float(remaining)
    order.status = status
    try:
        inv = order.invoice
        if inv is not None:
            inv.weight_closing_executed_weight = float(executed)
            inv.weight_closing_remaining_weight = float(remaining)
            inv.weight_closing_status = status
            db.session.add(inv)
    except Exception:
        pass
    db.session.add(order)


def _rollback_reservation(reservation: OfficeReservation, *, apply: bool):
    print(f"{'APPLY' if apply else 'PLAN'}: reset reservation fields res#{reservation.id} {reservation.reservation_code}")
    if not apply:
        return
    reservation.purchase_invoice_id = None
    reservation.executions_created = 0
    reservation.weight_consumed_main_karat = 0.0
    reservation.weight_remaining_main_karat = float(reservation.weight_main_karat or 0.0)
    reservation.status = "approved"
    db.session.add(reservation)


def _relink_vouchers_back(*, purchase_invoice_id: int | None, reservation_id: int, apply: bool):
    if not purchase_invoice_id:
        return
    vouchers = (
        db.session.query(Voucher)
        .filter(Voucher.reference_type == "invoice")
        .filter(Voucher.reference_id == int(purchase_invoice_id))
        .all()
    )
    if not vouchers:
        return

    print(f"{'APPLY' if apply else 'PLAN'}: relink vouchers count={len(vouchers)} invoice#{purchase_invoice_id} -> office_reservation#{reservation_id}")
    if not apply:
        return

    for v in vouchers:
        v.reference_type = "office_reservation"
        v.reference_id = int(reservation_id)
        try:
            v.reference_number = str(reservation_id)
        except Exception:
            pass
        db.session.add(v)


def _safe_delete_purchase_invoice(invoice_id: int | None, *, apply: bool) -> bool:
    if not invoice_id:
        return False
    inv = db.session.query(Invoice).filter(Invoice.id == int(invoice_id)).first()
    if not inv:
        return False

    # Safety gates
    if bool(getattr(inv, "is_posted", False)):
        print(f"SKIP: invoice#{inv.id} is_posted=True")
        return False

    # If any posted JE references this invoice, do not delete.
    posted_refs = (
        db.session.query(JournalEntry)
        .filter(JournalEntry.is_deleted == False)  # noqa: E712
        .filter(JournalEntry.reference_type == "invoice")
        .filter(JournalEntry.reference_id == int(inv.id))
        .filter(JournalEntry.is_posted == True)  # noqa: E712
        .count()
    )
    if posted_refs:
        print(f"SKIP: invoice#{inv.id} has posted JE references count={posted_refs}")
        return False

    order = db.session.query(WeightClosingOrder).filter(WeightClosingOrder.invoice_id == int(inv.id)).first()
    print(
        f"{'APPLY' if apply else 'PLAN'}: delete purchase invoice#{inv.id} (items + weight closing order={'yes' if order else 'no'})"
    )
    if not apply:
        return True

    # Delete non-cascading invoice items first.
    db.session.query(InvoiceItem).filter(InvoiceItem.invoice_id == int(inv.id)).delete(synchronize_session=False)
    if order is not None:
        db.session.delete(order)
    db.session.delete(inv)
    return True


def _recalculate_accounts(account_ids: set[int], *, apply: bool):
    """Recalculate impacted Account balances in-place.

    Important: Do NOT call helper scripts that commit per-account.
    Keep it atomic under this devtool's transaction.
    """
    if not apply:
        return
    if not account_ids:
        return

    print(f"APPLY: recalculate balances for {len(account_ids)} accounts")

    for aid in sorted(account_ids):
        account = db.session.query(Account).filter(Account.id == int(aid)).first()
        if not account:
            continue

        # Reset balances
        account.balance_cash = 0.0
        account.balance_18k = 0.0
        account.balance_21k = 0.0
        account.balance_22k = 0.0
        account.balance_24k = 0.0

        # Aggregate from JournalEntryLines
        rows = (
            db.session.query(JournalEntryLine)
            .join(JournalEntry)
            .filter(JournalEntryLine.account_id == int(account.id))
            .filter(JournalEntry.is_deleted == False)  # noqa: E712
            .filter(JournalEntry.is_draft == False)  # noqa: E712
            .filter(JournalEntryLine.is_deleted == False)  # noqa: E712
            .all()
        )

        for ln in rows:
            account.balance_cash += _as_float(getattr(ln, "cash_debit", 0.0)) - _as_float(getattr(ln, "cash_credit", 0.0))
            # Keep weights consistent even if tracks_weight flag is wrong in legacy DBs.
            account.balance_18k += _as_float(getattr(ln, "debit_18k", 0.0)) - _as_float(getattr(ln, "credit_18k", 0.0))
            account.balance_21k += _as_float(getattr(ln, "debit_21k", 0.0)) - _as_float(getattr(ln, "credit_21k", 0.0))
            account.balance_22k += _as_float(getattr(ln, "debit_22k", 0.0)) - _as_float(getattr(ln, "credit_22k", 0.0))
            account.balance_24k += _as_float(getattr(ln, "debit_24k", 0.0)) - _as_float(getattr(ln, "credit_24k", 0.0))

        db.session.add(account)


def _recalculate_suppliers_basic(supplier_ids: set[int], *, apply: bool):
    """Best-effort refresh of Supplier cached balances.

    This uses supplier_id tagging (not account filters). For office suppliers, this is typically
    sufficient because only the office account line is tagged with supplier_id.
    """
    if not apply:
        return
    if not supplier_ids:
        return

    from sqlalchemy import func

    for sid in sorted(supplier_ids):
        supplier = db.session.query(Supplier).filter(Supplier.id == int(sid)).first()
        if not supplier:
            continue

        rows = (
            db.session.query(
                (func.coalesce(func.sum(JournalEntryLine.cash_debit), 0.0) - func.coalesce(func.sum(JournalEntryLine.cash_credit), 0.0)).label("cash"),
                (func.coalesce(func.sum(JournalEntryLine.debit_18k), 0.0) - func.coalesce(func.sum(JournalEntryLine.credit_18k), 0.0)).label("b18"),
                (func.coalesce(func.sum(JournalEntryLine.debit_21k), 0.0) - func.coalesce(func.sum(JournalEntryLine.credit_21k), 0.0)).label("b21"),
                (func.coalesce(func.sum(JournalEntryLine.debit_22k), 0.0) - func.coalesce(func.sum(JournalEntryLine.credit_22k), 0.0)).label("b22"),
                (func.coalesce(func.sum(JournalEntryLine.debit_24k), 0.0) - func.coalesce(func.sum(JournalEntryLine.credit_24k), 0.0)).label("b24"),
                func.max(JournalEntry.date).label("last_dt"),
            )
            .join(JournalEntry)
            .filter(JournalEntry.is_deleted == False)  # noqa: E712
            .filter(JournalEntry.is_draft == False)  # noqa: E712
            .filter(JournalEntryLine.is_deleted == False)  # noqa: E712
            .filter(JournalEntryLine.supplier_id == int(sid))
            .first()
        )

        cash = _as_float(getattr(rows, "cash", 0.0))
        b18 = _as_float(getattr(rows, "b18", 0.0))
        b21 = _as_float(getattr(rows, "b21", 0.0))
        b22 = _as_float(getattr(rows, "b22", 0.0))
        b24 = _as_float(getattr(rows, "b24", 0.0))
        last_dt = getattr(rows, "last_dt", None)

        supplier.balance_cash = round(cash, 2)
        supplier.balance_gold_18k = round(b18, 3)
        supplier.balance_gold_21k = round(b21, 3)
        supplier.balance_gold_22k = round(b22, 3)
        supplier.balance_gold_24k = round(b24, 3)
        if last_dt is not None:
            supplier.last_gold_transaction_date = last_dt
        db.session.add(supplier)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Rollback office reservation to before a given JournalEntry")
    p.add_argument("--reservation-id", type=int, required=True)
    p.add_argument("--before-entry-id", type=int, default=None, help="Include office_reservation JEs with id >= this")
    p.add_argument(
        "--entry-ids",
        nargs="*",
        type=int,
        default=None,
        help="Explicit JE ids to rollback (overrides --before-entry-id). Example: --entry-ids 112 113",
    )
    p.add_argument("--mode", choices=["soft-delete", "reverse"], default="soft-delete")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--posted-by", default="system")
    p.add_argument("--deleted-by", default="system")
    args = p.parse_args(argv)

    apply = bool(args.apply)

    with app.app_context():
        reservation = (
            db.session.query(OfficeReservation)
            .filter(OfficeReservation.id == int(args.reservation_id))
            .first()
        )
        if not reservation:
            print("NOT FOUND: reservation")
            return 2

        entry_ids = [int(x) for x in (args.entry_ids or []) if x is not None]
        entries = _get_office_reservation_entries(int(reservation.id), args.before_entry_id, entry_ids)
        if not entries:
            print("NOT FOUND: no posted office_reservation journal entries in scope")
            return 2

        print(
            f"INFO: reservation res#{reservation.id} code={reservation.reservation_code} entries_in_scope={len(entries)} mode={args.mode} apply={apply}"
        )

        entry_ids = [int(e.id) for e in entries]
        purchase_invoice_id = getattr(reservation, "purchase_invoice_id", None)

        impacted_accounts: set[int] = set()
        supplier_ids: set[int] = set()

        # Collect impacted accounts and suppliers from the affected JEs.
        for je in entries:
            for ln in _get_entry_lines(int(je.id)):
                try:
                    impacted_accounts.add(int(ln.account_id))
                except Exception:
                    pass
                try:
                    if getattr(ln, "supplier_id", None):
                        supplier_ids.add(int(ln.supplier_id))
                except Exception:
                    pass

        # 1) Undo weight-closing executions tied to these JEs.
        affected_orders = _delete_weight_closing_executions_for_entries(entry_ids, apply=apply)

        # 2) Rollback journal entries (soft-delete or reversal).
        if args.mode == "reverse":
            for je in entries:
                _reverse_journal_entry(reservation=reservation, original=je, posted_by=str(args.posted_by), apply=apply)
        else:
            impacted_accounts |= _soft_delete_entries(
                entries,
                deleted_by=str(args.deleted_by),
                reason=f"rollback to before JE>=#{args.before_entry_id or 'ALL'} for office reservation #{reservation.id}",
                apply=apply,
            )

        # 3) Recompute affected orders after deleting executions.
        for oid in sorted(affected_orders):
            _recompute_weight_closing_order(int(oid), apply=apply)

        # 4) Revert reservation fields and relink vouchers.
        _relink_vouchers_back(
            purchase_invoice_id=int(purchase_invoice_id) if purchase_invoice_id else None,
            reservation_id=int(reservation.id),
            apply=apply,
        )
        _rollback_reservation(reservation, apply=apply)

        # 5) Delete purchase invoice when safe.
        _safe_delete_purchase_invoice(int(purchase_invoice_id) if purchase_invoice_id else None, apply=apply)

        # 6) Balances refresh
        if args.mode == "soft-delete":
            _recalculate_accounts(impacted_accounts, apply=apply)
        _recalculate_suppliers_basic(supplier_ids, apply=apply)

        if apply:
            db.session.commit()
            print("DONE: rollback applied")
        else:
            db.session.rollback()
            print("DRY RUN: no changes written")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
