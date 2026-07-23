#!/usr/bin/env python3
"""ERP Seam Ratchet — ADR-023 enforcement.

Reads docs/architecture/erp-seam-ledger.md and counts:
  - total: rows in the Ledger table (integration touches)
  - tested: rows where "Contract Tests" column contains ✅

Compares to the committed baseline in docs/architecture/.erp-seam-ratchet.
Fails (exit 1) if the coverage ratio has decreased.

Usage:
    python scripts/erp_seam_ratchet.py            # check + print
    python scripts/erp_seam_ratchet.py --update   # check + update baseline if improved
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
LEDGER    = REPO_ROOT / "docs" / "architecture" / "erp-seam-ledger.md"
BASELINE  = REPO_ROOT / "docs" / "architecture" / ".erp-seam-ratchet"


def _parse_ledger(text: str) -> tuple[int, int]:
    """Return (tested, total) by reading the Ledger table rows."""
    total = 0
    tested = 0
    in_table = False
    header_skipped = False

    for line in text.splitlines():
        stripped = line.strip()
        # Detect start of Ledger table (the header row)
        if stripped.startswith("| #") and "ERP File" in stripped:
            in_table = True
            header_skipped = False
            continue
        if not in_table:
            continue
        # Skip the separator row (|---|---|...)
        if re.match(r"^\|[-| ]+\|$", stripped):
            header_skipped = True
            continue
        # A Markdown heading ends the table; a blank line is just formatting — skip it
        if stripped.startswith("#"):
            in_table = False
            continue
        if not stripped:
            continue
        # Stop at the "Pending Rows" section (lower-priority table)
        if "Pending Rows" in stripped or "Expected Touch" in stripped:
            break
        # Data row
        if stripped.startswith("|") and header_skipped:
            cols = [c.strip() for c in stripped.split("|")]
            # Table: # | File | Date | Touch | Raised | ContractTests | PR |
            # Cells may contain \| so column count varies.
            # "Contract Tests" is always second-to-last (before PR, before trailing '').
            # cols[-1]='' cols[-2]=PR cols[-3]=ContractTests
            if len(cols) >= 5:
                total += 1
                if "✅" in cols[-3]:
                    tested += 1

    return tested, total


def _parse_baseline(text: str) -> tuple[int, int]:
    """Return (tested, total) from baseline file."""
    data: dict[str, int] = {}
    for line in text.splitlines():
        line = line.strip()
        if "=" in line:
            k, _, v = line.partition("=")
            data[k.strip()] = int(v.strip())
    return data.get("tested", 0), data.get("total", 0)


def _ratio_ok(tested: int, total: int, base_tested: int, base_total: int) -> bool:
    """Return True if tested/total >= base_tested/base_total (cross-multiplication, no floats)."""
    if total == 0:
        return True
    if base_total == 0:
        return True
    # tested/total >= base_tested/base_total
    # ⟺ tested * base_total >= base_tested * total
    return tested * base_total >= base_tested * total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true",
                        help="Update baseline if coverage improved")
    args = parser.parse_args(argv)

    if not LEDGER.exists():
        print(f"ERROR: Ledger not found at {LEDGER}", file=sys.stderr)
        return 1

    ledger_text   = LEDGER.read_text(encoding="utf-8")
    tested, total = _parse_ledger(ledger_text)

    pct = f"{tested * 100 // total}%" if total > 0 else "n/a"
    print(f"ERP seam ratchet: {tested}/{total} routes have contract tests ({pct})")

    if not BASELINE.exists():
        print("WARNING: No baseline file — writing initial baseline.", file=sys.stderr)
        BASELINE.write_text(f"tested={tested}\ntotal={total}\n", encoding="utf-8")
        return 0

    base_tested, base_total = _parse_baseline(BASELINE.read_text(encoding="utf-8"))
    base_pct = (
        f"{base_tested * 100 // base_total}%" if base_total > 0 else "n/a"
    )
    print(f"ERP seam baseline: {base_tested}/{base_total} ({base_pct})")

    if not _ratio_ok(tested, total, base_tested, base_total):
        print(
            f"\n❌ RATCHET VIOLATION (ADR-023 M1): coverage dropped from "
            f"{base_tested}/{base_total} to {tested}/{total}.\n"
            f"   Every integration touch must include contract tests.\n"
            f"   Add tests or update the Ledger row, then re-run.",
            file=sys.stderr,
        )
        return 1

    print("✅ Ratchet: OK")

    if args.update and (tested > base_tested or total != base_total):
        BASELINE.write_text(f"tested={tested}\ntotal={total}\n", encoding="utf-8")
        print(f"   Baseline updated → {tested}/{total}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
