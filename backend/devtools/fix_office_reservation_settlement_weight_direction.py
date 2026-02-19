#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Fix office-reservation settlement weight direction.

Problem
- Older deployments may have posted office-reservation settlement JEs with the *opposite* weight direction.
- New intended convention (current code):
  - Inventory: credit weight (gold leaves inventory)
  - Office account: debit weight (office owes us gold until delivery)

This script detects office-reservation settlement JEs and can post a balancing *adjustment* JE that flips
the weight direction without touching cash amounts.

Safety
- Default is DRY RUN (no DB writes).
- Use --apply to commit.

Usage
  cd backend
    # Ensure the script points to your production DB by exporting DATABASE_URL.
    # Examples:
    #   export DATABASE_URL='sqlite:////absolute/path/to/app.db'
    #   export DATABASE_URL='postgresql://user:pass@host:5432/dbname'
  BYPASS_AUTH_FOR_DEVELOPMENT=1 ./venv/bin/python devtools/fix_office_reservation_settlement_weight_direction.py

  BYPASS_AUTH_FOR_DEVELOPMENT=1 ./venv/bin/python devtools/fix_office_reservation_settlement_weight_direction.py --apply

Filters
  --reservation-id <id>
  --office-id <id>
  --since YYYY-MM-DD
  --until YYYY-MM-DD
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
from dual_system_helpers import create_dual_journal_entry  # noqa: E402
from models import Account, JournalEntry, JournalEntryLine, Office, OfficeReservation, db  # noqa: E402
from office_supplier_service import ensure_office_supplier  # noqa: E402


_KARATS: tuple[int, ...] = (18, 21, 22, 24)


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
    # Prefer the explicit inventory line description.
    for ln in lines:
        if office_line is not None and int(ln.account_id) == int(office_line.account_id):
            continue
        desc = (ln.description or "").strip()
        if "إخراج وزن من المخزون" in desc:
            return ln

    # Fallback: a line with cash_debit matching typical settlement pattern.
    candidates = []
    for ln in lines:
        if office_line is not None and int(ln.account_id) == int(office_line.account_id):
            continue
        if _as_float(getattr(ln, "cash_debit", 0.0)) > 0 and _as_float(getattr(ln, "cash_credit", 0.0)) <= 0:
            candidates.append(ln)

    return candidates[0] if candidates else None


def _karat_weights(line: JournalEntryLine, k: int) -> tuple[float, float]:
    return (
        _as_float(getattr(line, f"debit_{k}k", 0.0)),
        _as_float(getattr(line, f"credit_{k}k", 0.0)),
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Fix legacy office-reservation settlement weight direction")
    parser.add_argument("--apply", action="store_true", help="Apply changes (commit). Default: dry-run")
    parser.add_argument(
        "--target",
        choices=("office_debit", "office_credit"),
        default="office_debit",
        help=(
            "Desired final direction for the OFFICE line's weight. "
            "office_debit = office owes us weight (current convention). "
            "office_credit = office is owed weight (legacy)."
        ),
    )
    parser.add_argument("--reservation-id", type=int, default=None, help="Only fix this OfficeReservation ID")
    parser.add_argument("--office-id", type=int, default=None, help="Only fix reservations for this Office ID")
    parser.add_argument("--since", default=None, help="Start date (YYYY-MM-DD), inclusive")
    parser.add_argument("--until", default=None, help="End date (YYYY-MM-DD), inclusive")
    parser.add_argument("--limit", type=int, default=None, help="Max number of JEs to inspect")
    parser.add_argument("--posted-by", default="system", help="posted_by for created adjustment entries")
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

            # Detect direction per-karat (we only auto-fix when pattern is clean).
            to_flip: list[tuple[int, float]] = []
            already_in_target = False

            for k in _KARATS:
                off_d, off_c = _karat_weights(office_line, k)
                inv_d, inv_c = _karat_weights(inventory_line, k)

                # Current convention: office debit, inventory credit.
                is_office_debit = (off_d > 0 and off_c <= 0 and inv_c > 0 and inv_d <= 0 and abs(inv_c - off_d) <= 0.001)
                # Legacy convention: office credit, inventory debit.
                is_office_credit = (off_c > 0 and off_d <= 0 and inv_d > 0 and inv_c <= 0 and abs(inv_d - off_c) <= 0.001)

                if args.target == "office_debit":
                    if is_office_debit:
                        already_in_target = True
                        continue
                    if is_office_credit:
                        to_flip.append((k, off_c))
                else:
                    if is_office_credit:
                        already_in_target = True
                        continue
                    if is_office_debit:
                        to_flip.append((k, off_d))

            if already_in_target and to_flip:
                # Mixed state: don't touch automatically.
                print(f"SKIP (mixed): JE#{je.id} res#{reservation.id} code={reservation.reservation_code} office='{office.name}'")
                skipped += 1
                continue

            if not to_flip:
                continue

            planned += 1

            summary = ", ".join([f"{k}k:{w:.3f}g" for k, w in to_flip])
            print(
                f"{'APPLY' if apply else 'PLAN'}: Fix JE#{je.id} res#{reservation.id} ({reservation.reservation_code}) "
                f"office='{office.name}' weights=[{summary}]"
            )

            if not apply:
                continue

            supplier = ensure_office_supplier(office)

            adj = JournalEntry(
                date=je.date,
                description=(
                    f"تصحيح اتجاه الوزن (تسوية مكتب قديمة) - {reservation.reservation_code} - JE#{je.id}"
                ),
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

            for k, w in to_flip:
                correction = float(w) * 2.0
                karat_debit = f"debit_{k}k"
                karat_credit = f"credit_{k}k"

                if args.target == "office_debit":
                    # Flip legacy -> current: Inventory credit, Office debit.
                    create_dual_journal_entry(
                        journal_entry_id=adj.id,
                        account_id=int(inventory_line.account_id),
                        description=f"تصحيح اتجاه الوزن - مخزون ({k}k)",
                        exclude_from_ledger=True,
                        **{karat_credit: correction},
                    )
                    create_dual_journal_entry(
                        journal_entry_id=adj.id,
                        account_id=int(office.account_category_id),
                        supplier_id=int(supplier.id) if supplier else None,
                        description=f"تصحيح اتجاه الوزن - مكتب ({k}k)",
                        **{karat_debit: correction},
                    )
                else:
                    # Flip current -> legacy: Inventory debit, Office credit.
                    create_dual_journal_entry(
                        journal_entry_id=adj.id,
                        account_id=int(inventory_line.account_id),
                        description=f"تصحيح اتجاه الوزن - مخزون ({k}k)",
                        exclude_from_ledger=True,
                        **{karat_debit: correction},
                    )
                    create_dual_journal_entry(
                        journal_entry_id=adj.id,
                        account_id=int(office.account_category_id),
                        supplier_id=int(supplier.id) if supplier else None,
                        description=f"تصحيح اتجاه الوزن - مكتب ({k}k)",
                        **{karat_credit: correction},
                    )

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
