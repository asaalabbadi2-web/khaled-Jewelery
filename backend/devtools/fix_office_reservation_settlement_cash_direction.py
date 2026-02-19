#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Fix office-reservation settlement cash direction.

Problem
- Older deployments may have posted office-reservation settlement JEs with the *opposite* cash direction.
- Current intended convention (current code in routes.py):
  - Inventory: cash_debit (increase inventory at cost)
  - Office account: cash_credit (payable / liability to the office)

This script detects office-reservation settlement JEs and posts a balancing *adjustment* JE that flips
ONLY the cash direction (does not touch weights).

Safety
- Default is DRY RUN (no DB writes).
- Use --apply to commit.
- The script will skip a reservation if it finds a prior posted adjustment with the same reference
  and a matching "تصحيح اتجاه النقد" marker, to avoid double-fixing.

Usage
  cd backend
  BYPASS_AUTH_FOR_DEVELOPMENT=1 ./venv/bin/python devtools/fix_office_reservation_settlement_cash_direction.py
  BYPASS_AUTH_FOR_DEVELOPMENT=1 ./venv/bin/python devtools/fix_office_reservation_settlement_cash_direction.py --apply

Filters
  --reservation-id <id>
  --office-id <id>
  --since YYYY-MM-DD
  --until YYYY-MM-DD
  --limit N
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta

os.environ.setdefault("BYPASS_AUTH_FOR_DEVELOPMENT", "1")

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app import app  # noqa: E402
from dual_system_helpers import create_dual_journal_entry, verify_dual_balance  # noqa: E402
from models import JournalEntry, JournalEntryLine, Office, OfficeReservation, db  # noqa: E402
from office_supplier_service import ensure_office_supplier  # noqa: E402


_ADJ_MARKER = "تصحيح اتجاه النقد"


def _as_float(v) -> float:
    try:
        return float(v or 0.0)
    except Exception:
        return 0.0


def _parse_date(s: str | None, *, end: bool = False) -> datetime | None:
    if not s:
        return None
    s = str(s).strip()
    if not s:
        return None
    dt = datetime.strptime(s, "%Y-%m-%d")
    if end:
        return dt + timedelta(days=1)
    return dt


def _pick_office_line(lines: list[JournalEntryLine], office_account_id: int) -> JournalEntryLine | None:
    for ln in lines:
        if int(ln.account_id) == int(office_account_id):
            return ln
    for ln in lines:
        desc = (ln.description or "").strip()
        if "ذهب لدى مكتب التسكير" in desc:
            return ln
    return None


def _pick_inventory_line(lines: list[JournalEntryLine], *, office_line: JournalEntryLine | None) -> JournalEntryLine | None:
    for ln in lines:
        if office_line is not None and int(ln.account_id) == int(office_line.account_id):
            continue
        desc = (ln.description or "").strip()
        if "إخراج وزن من المخزون" in desc:
            return ln

    candidates: list[JournalEntryLine] = []
    for ln in lines:
        if office_line is not None and int(ln.account_id) == int(office_line.account_id):
            continue
        # Heuristic: inventory line typically has the opposite cash sign from the office line.
        if _as_float(getattr(ln, "cash_debit", 0.0)) > 0 and _as_float(getattr(ln, "cash_credit", 0.0)) <= 0:
            candidates.append(ln)
        elif _as_float(getattr(ln, "cash_credit", 0.0)) > 0 and _as_float(getattr(ln, "cash_debit", 0.0)) <= 0:
            candidates.append(ln)

    return candidates[0] if candidates else None


def _has_prior_cash_adjustment(reservation_id: int, *, exclude_je_id: int) -> bool:
    try:
        q = JournalEntry.query.filter(JournalEntry.is_deleted == False)  # noqa: E712
        q = q.filter(JournalEntry.reference_type == "office_reservation")
        q = q.filter(JournalEntry.reference_id == int(reservation_id))
        q = q.filter(JournalEntry.is_posted == True)  # noqa: E712
        q = q.filter(JournalEntry.id != int(exclude_je_id))

        # A light marker-based check. We avoid heavy line-summing here.
        q = q.filter(JournalEntry.description.ilike(f"%{_ADJ_MARKER}%"))
        return q.first() is not None
    except Exception:
        return False


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Fix legacy office-reservation settlement cash direction")
    parser.add_argument("--apply", action="store_true", help="Apply changes (commit). Default: dry-run")
    parser.add_argument(
        "--target",
        choices=("office_credit", "office_debit"),
        default="office_credit",
        help=(
            "Desired final direction for the OFFICE line's cash. "
            "office_credit = office payable (current convention). "
            "office_debit = legacy (office has debit)."
        ),
    )
    parser.add_argument("--reservation-id", type=int, default=None, help="Only fix this OfficeReservation ID")
    parser.add_argument("--office-id", type=int, default=None, help="Only fix reservations for this Office ID")
    parser.add_argument("--since", default=None, help="Start date (YYYY-MM-DD), inclusive")
    parser.add_argument("--until", default=None, help="End date (YYYY-MM-DD), inclusive")
    parser.add_argument("--limit", type=int, default=None, help="Max number of JEs to inspect")
    parser.add_argument("--posted-by", default="system", help="posted_by for created adjustment entries")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Apply even if a prior cash adjustment entry is detected (not recommended)",
    )
    args = parser.parse_args(argv)

    since_dt = _parse_date(args.since)
    until_dt = _parse_date(args.until, end=True)

    apply = bool(args.apply)

    with app.app_context():
        q = JournalEntry.query.filter(JournalEntry.is_deleted == False)  # noqa: E712
        q = q.filter(JournalEntry.reference_type == "office_reservation")
        q = q.filter(JournalEntry.is_posted == True)  # noqa: E712
        q = q.filter(JournalEntry.is_draft == False)  # noqa: E712

        if since_dt is not None:
            q = q.filter(JournalEntry.date >= since_dt)
        if until_dt is not None:
            q = q.filter(JournalEntry.date < until_dt)

        q = q.order_by(JournalEntry.date.asc(), JournalEntry.id.asc())

        if args.limit is not None:
            q = q.limit(max(0, int(args.limit)))

        entries: list[JournalEntry] = list(q.all())

        inspected = 0
        planned = 0
        applied = 0
        skipped = 0

        for je in entries:
            inspected += 1

            res_id = getattr(je, "reference_id", None)
            try:
                res_id_int = int(res_id) if res_id is not None else None
            except Exception:
                res_id_int = None

            if res_id_int is None:
                skipped += 1
                continue

            reservation = OfficeReservation.query.get(res_id_int)
            if not reservation:
                skipped += 1
                continue

            if args.reservation_id is not None and int(reservation.id) != int(args.reservation_id):
                continue

            if args.office_id is not None and int(reservation.office_id) != int(args.office_id):
                continue

            office = Office.query.get(int(reservation.office_id))
            if not office or not office.account_category_id:
                skipped += 1
                continue

            if not args.force and _has_prior_cash_adjustment(int(reservation.id), exclude_je_id=int(je.id)):
                # Already fixed (or at least an adjustment exists); avoid double-fixing.
                continue

            lines = [ln for ln in (je.lines or []) if not getattr(ln, "is_deleted", False)]
            if not lines:
                skipped += 1
                continue

            office_line = _pick_office_line(lines, int(office.account_category_id))
            if not office_line:
                skipped += 1
                continue

            inventory_line = _pick_inventory_line(lines, office_line=office_line)
            if not inventory_line:
                skipped += 1
                continue

            off_cd = _as_float(getattr(office_line, "cash_debit", 0.0))
            off_cc = _as_float(getattr(office_line, "cash_credit", 0.0))
            inv_cd = _as_float(getattr(inventory_line, "cash_debit", 0.0))
            inv_cc = _as_float(getattr(inventory_line, "cash_credit", 0.0))

            # Current convention: office credit, inventory debit.
            is_office_credit = (off_cc > 0 and off_cd <= 0 and inv_cd > 0 and inv_cc <= 0 and abs(inv_cd - off_cc) <= 0.01)
            # Legacy convention: office debit, inventory credit.
            is_office_debit = (off_cd > 0 and off_cc <= 0 and inv_cc > 0 and inv_cd <= 0 and abs(inv_cc - off_cd) <= 0.01)

            if args.target == "office_credit":
                if is_office_credit:
                    continue
                if not is_office_debit:
                    # Unknown/mixed pattern
                    skipped += 1
                    continue
                amount = off_cd
            else:
                if is_office_debit:
                    continue
                if not is_office_credit:
                    skipped += 1
                    continue
                amount = off_cc

            if amount <= 0:
                skipped += 1
                continue

            planned += 1
            print(
                f"{'APPLY' if apply else 'PLAN'}: Fix cash JE#{je.id} res#{reservation.id} ({reservation.reservation_code}) "
                f"office='{office.name}' amount={amount:.2f}"
            )

            if not apply:
                continue

            supplier = ensure_office_supplier(office)

            adj = JournalEntry(
                date=je.date,
                description=f"{_ADJ_MARKER} (تسوية مكتب قديمة) - {reservation.reservation_code} - JE#{je.id}",
                entry_type="تصحيح",
                reference_type="office_reservation",
                reference_id=int(reservation.id),
                is_posted=True,
                posted_at=je.date,
                posted_by=str(args.posted_by or "system"),
                created_by=str(args.posted_by or "system"),
            )
            db.session.add(adj)
            db.session.flush()

            correction = float(amount) * 2.0

            if args.target == "office_credit":
                # Flip legacy -> current: Inventory debit, Office credit.
                create_dual_journal_entry(
                    journal_entry_id=adj.id,
                    account_id=int(inventory_line.account_id),
                    cash_debit=correction,
                    description="تصحيح اتجاه النقد - مخزون",
                    exclude_from_ledger=True,
                    apply_golden_rule=False,
                )
                create_dual_journal_entry(
                    journal_entry_id=adj.id,
                    account_id=int(office.account_category_id),
                    cash_credit=correction,
                    supplier_id=int(supplier.id) if supplier else None,
                    description="تصحيح اتجاه النقد - مكتب",
                    apply_golden_rule=False,
                )
            else:
                # Flip current -> legacy: Inventory credit, Office debit.
                create_dual_journal_entry(
                    journal_entry_id=adj.id,
                    account_id=int(inventory_line.account_id),
                    cash_credit=correction,
                    description="تصحيح اتجاه النقد - مخزون",
                    exclude_from_ledger=True,
                    apply_golden_rule=False,
                )
                create_dual_journal_entry(
                    journal_entry_id=adj.id,
                    account_id=int(office.account_category_id),
                    cash_debit=correction,
                    supplier_id=int(supplier.id) if supplier else None,
                    description="تصحيح اتجاه النقد - مكتب",
                    apply_golden_rule=False,
                )

            verify_dual_balance(adj.id)
            applied += 1

        if apply:
            db.session.commit()
            print(f"DONE: applied={applied} planned={planned} inspected={inspected} skipped={skipped}")
        else:
            db.session.rollback()
            print(f"DRY RUN: planned={planned} inspected={inspected} skipped={skipped}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
