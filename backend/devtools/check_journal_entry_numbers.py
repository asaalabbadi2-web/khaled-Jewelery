"""Check JournalEntry.entry_number consistency.

Reports:
- Duplicate entry_number values
- entry_number year that doesn't match JournalEntry.date.year
- Missing sequence numbers per year for the default JE prefix (JE-YYYY-xxxxx)

Read-only.

Usage:
  ./venv/bin/python devtools/check_journal_entry_numbers.py
  ./venv/bin/python devtools/check_journal_entry_numbers.py --year 2026
  ./venv/bin/python devtools/check_journal_entry_numbers.py --show-missing 200
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from typing import Iterable

from sqlalchemy import func

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from app import app
from models import JournalEntry


_JE_RE = re.compile(r"^(?P<prefix>[A-Z]{1,10})-(?P<year>\d{4})-(?P<seq>\d{1,10})$")


def _parse(entry_number: str):
    m = _JE_RE.match(str(entry_number or "").strip())
    if not m:
        return None
    try:
        return {
            "prefix": m.group("prefix"),
            "year": int(m.group("year")),
            "seq": int(m.group("seq")),
        }
    except Exception:
        return None


def _iter_entries(year: int | None) -> Iterable[JournalEntry]:
    q = JournalEntry.query
    if year is not None:
        # Portable across SQLite/PostgreSQL.
        start = datetime(year, 1, 1)
        end = datetime(year + 1, 1, 1)
        q = q.filter(JournalEntry.date >= start, JournalEntry.date < end)
    return q.order_by(JournalEntry.id.asc()).all()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=None, help="Limit checks to a specific date-year")
    parser.add_argument(
        "--show-missing",
        type=int,
        default=50,
        help="How many missing sequence numbers to show per year (JE only)",
    )
    args = parser.parse_args()

    with app.app_context():
        # 1) Duplicates (all prefixes)
        dup_q = (
            JournalEntry.query.with_entities(JournalEntry.entry_number, func.count(JournalEntry.id))
            .group_by(JournalEntry.entry_number)
            .having(func.count(JournalEntry.id) > 1)
            .order_by(func.count(JournalEntry.id).desc())
        )
        if args.year is not None:
            start = datetime(args.year, 1, 1)
            end = datetime(args.year + 1, 1, 1)
            dup_q = dup_q.filter(JournalEntry.date >= start, JournalEntry.date < end)

        duplicates = list(dup_q.all())
        print("=== Duplicate entry_number ===")
        if not duplicates:
            print("OK: no duplicates")
        else:
            for entry_number, cnt in duplicates[:100]:
                ids = [
                    r[0]
                    for r in JournalEntry.query.with_entities(JournalEntry.id)
                    .filter(JournalEntry.entry_number == entry_number)
                    .order_by(JournalEntry.id.asc())
                    .all()
                ]
                print(f"{entry_number}  count={cnt}  ids={ids}")
            if len(duplicates) > 100:
                print(f"... and {len(duplicates) - 100} more")

        # 2) Year mismatch (JE format only)
        print("\n=== entry_number year != date.year (parsed formats) ===")
        mismatches = []
        for je in _iter_entries(args.year):
            p = _parse(je.entry_number)
            if not p:
                continue
            if je.date and p["year"] != int(je.date.year):
                mismatches.append((je.id, je.entry_number, je.date.isoformat()))

        if not mismatches:
            print("OK: no mismatches")
        else:
            for row in mismatches[:200]:
                print(f"id={row[0]}  entry_number={row[1]}  date={row[2]}")
            if len(mismatches) > 200:
                print(f"... and {len(mismatches) - 200} more")

        # 3) Missing sequences for JE prefix
        print("\n=== Missing JE sequences per year ===")
        seq_by_year: dict[int, set[int]] = defaultdict(set)
        for je in _iter_entries(args.year):
            p = _parse(je.entry_number)
            if not p or p["prefix"] != "JE":
                continue
            seq_by_year[p["year"]].add(p["seq"])

        if not seq_by_year:
            print("No JE entries found")
        else:
            for year in sorted(seq_by_year.keys()):
                seqs = sorted(seq_by_year[year])
                if not seqs:
                    continue
                min_seq, max_seq = seqs[0], seqs[-1]
                missing = [i for i in range(min_seq, max_seq + 1) if i not in seq_by_year[year]]
                print(f"{year}: min={min_seq} max={max_seq} missing={len(missing)}")
                if missing:
                    shown = missing[: max(0, int(args.show_missing))]
                    print("  " + ", ".join(str(x) for x in shown))
                    if len(missing) > len(shown):
                        print(f"  ... and {len(missing) - len(shown)} more")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
