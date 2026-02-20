#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Inspect a journal entry and its lines (read-only).

Use this to debug production mismatches by printing the exact JE header + lines
(account, cash, weights, supplier/customer ids).

Examples
  cd backend
  BYPASS_AUTH_FOR_DEVELOPMENT=1 ./venv/bin/python devtools/inspect_journal_entry.py --entry-number WGT-2026-00001
  BYPASS_AUTH_FOR_DEVELOPMENT=1 ./venv/bin/python devtools/inspect_journal_entry.py --entry-number JE-2026-00078

You can also inspect by reference:
  BYPASS_AUTH_FOR_DEVELOPMENT=1 ./venv/bin/python devtools/inspect_journal_entry.py --reference-type office_reservation --reference-id 123

Notes
- This script does NOT modify anything.
- Point it at production DB via DATABASE_URL env var.
"""

from __future__ import annotations

import argparse
import os
import sys

os.environ.setdefault("BYPASS_AUTH_FOR_DEVELOPMENT", "1")

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app import app  # noqa: E402
from models import Account, JournalEntry, JournalEntryLine, db  # noqa: E402


def _f(v, ndigits: int = 3) -> str:
    try:
        x = float(v or 0.0)
    except Exception:
        x = 0.0
    fmt = f"{{:.{ndigits}f}}"
    return fmt.format(x)


def _line_weights(ln: JournalEntryLine) -> str:
    parts = []
    for k in (18, 21, 22, 24):
        d = float(getattr(ln, f"debit_{k}k", 0.0) or 0.0)
        c = float(getattr(ln, f"credit_{k}k", 0.0) or 0.0)
        if abs(d) > 1e-9 or abs(c) > 1e-9:
            parts.append(f"{k}k D={_f(d)} C={_f(c)}")
    return " | ".join(parts) if parts else "-"


def _print_entry(je: JournalEntry) -> None:
    print("=" * 90)
    print(f"JE id={je.id} entry_number={je.entry_number} date={je.date} posted={je.is_posted} draft={je.is_draft} deleted={je.is_deleted}")
    print(f"ref={je.reference_type}:{je.reference_id} type={je.entry_type} desc={je.description}")

    lines = (
        db.session.query(JournalEntryLine)
        .filter(JournalEntryLine.journal_entry_id == je.id)
        .filter((JournalEntryLine.is_deleted == False) | (JournalEntryLine.is_deleted.is_(None)))  # noqa: E712
        .order_by(JournalEntryLine.id.asc())
        .all()
    )

    if not lines:
        print("(no lines)")
        return

    account_ids = {int(ln.account_id) for ln in lines if ln.account_id is not None}
    accounts = db.session.query(Account).filter(Account.id.in_(sorted(account_ids))).all()
    acc_map = {int(a.id): a for a in accounts}

    for ln in lines:
        acc = acc_map.get(int(ln.account_id)) if ln.account_id is not None else None
        acc_no = getattr(acc, "account_number", None)
        acc_name = getattr(acc, "name", None)

        cd = float(getattr(ln, "cash_debit", 0.0) or 0.0)
        cc = float(getattr(ln, "cash_credit", 0.0) or 0.0)

        print("-" * 90)
        print(f"LN id={ln.id} acc_id={ln.account_id} acc_no={acc_no} acc_name={acc_name}")
        print(f"  cash: D={_f(cd,2)} C={_f(cc,2)}  supplier_id={ln.supplier_id} customer_id={ln.customer_id}")
        print(f"  weights: {_line_weights(ln)}")
        d = (ln.description or "").strip()
        if d:
            print(f"  desc: {d}")


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Inspect a journal entry and its lines (read-only)")
    p.add_argument("--entry-number", default=None, help="JournalEntry.entry_number (e.g. JE-2026-00078, WGT-2026-00001)")
    p.add_argument("--id", type=int, default=None, help="JournalEntry.id")
    p.add_argument("--reference-type", default=None, help="JournalEntry.reference_type")
    p.add_argument("--reference-id", type=int, default=None, help="JournalEntry.reference_id")
    args = p.parse_args(argv)

    if not args.entry_number and not args.id and not (args.reference_type and args.reference_id):
        p.error("Provide --entry-number or --id or (--reference-type and --reference-id)")

    with app.app_context():
        q = db.session.query(JournalEntry)
        q = q.filter(JournalEntry.is_deleted == False)  # noqa: E712

        if args.id:
            je = q.filter(JournalEntry.id == int(args.id)).first()
            if not je:
                print("NOT FOUND")
                return 2
            _print_entry(je)
            return 0

        if args.entry_number:
            je = q.filter(JournalEntry.entry_number == str(args.entry_number)).first()
            if not je:
                print("NOT FOUND")
                return 2
            _print_entry(je)
            return 0

        q = q.filter(JournalEntry.reference_type == str(args.reference_type))
        q = q.filter(JournalEntry.reference_id == int(args.reference_id))
        entries = q.order_by(JournalEntry.date.asc(), JournalEntry.id.asc()).all()
        if not entries:
            print("NOT FOUND")
            return 2
        for je in entries:
            _print_entry(je)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
