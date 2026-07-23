"""Unit tests for scripts/erp_seam_ratchet.py parser.

Law 0: a gate without a test is a comment.
The ratchet itself must be guarded so that table-formatting
decisions (blank lines between rows, pipe chars inside cells)
cannot silently under-count seam coverage.

A2 from Sprint 9 close: the original parser exited in_table=False
on any blank line, so rows after a blank line were silently dropped.
These tests must be RED against the buggy parser and GREEN after the fix.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Allow importing from scripts/ without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
from erp_seam_ratchet import _parse_ledger  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_table(*rows: str, pending: bool = False) -> str:
    """Build a minimal Ledger-style Markdown table from data rows."""
    header = "| # | ERP File | Date | Touch | Raised | Contract Tests | PR |"
    sep    = "|---|---|---|---|---|---|---|"
    body   = "\n".join(rows)
    result = f"{header}\n{sep}\n{body}\n"
    if pending:
        result += "\n## Pending Rows\n"
    return result


def _row(n: int, tested: bool = True) -> str:
    ct = "✅" if tested else "🔴"
    return f"| {n} | backend/file.py | 2026-07 | Add | DONE | {ct} | PR#1 |"


# ---------------------------------------------------------------------------
# Basic counting
# ---------------------------------------------------------------------------

class TestBasicCounting:
    def test_single_tested_row(self):
        text = _make_table(_row(1, tested=True))
        assert _parse_ledger(text) == (1, 1)

    def test_single_untested_row(self):
        text = _make_table(_row(1, tested=False))
        assert _parse_ledger(text) == (0, 1)

    def test_two_rows_both_tested(self):
        text = _make_table(_row(1), _row(2))
        assert _parse_ledger(text) == (2, 2)

    def test_mixed_tested_untested(self):
        text = _make_table(_row(1, True), _row(2, False), _row(3, True))
        assert _parse_ledger(text) == (2, 3)

    def test_empty_table_no_rows(self):
        header = "| # | ERP File | Date | Touch | Raised | Contract Tests | PR |"
        sep    = "|---|---|---|---|---|---|---|"
        text   = f"{header}\n{sep}\n"
        assert _parse_ledger(text) == (0, 0)


# ---------------------------------------------------------------------------
# A2 regression: blank lines between rows must NOT stop counting
# ---------------------------------------------------------------------------

class TestBlankLineBetweenRows:
    """These are the load-bearing A2 tests — RED against the buggy parser."""

    def test_blank_line_between_rows_still_counted(self):
        """A blank line between row 1 and row 2 must not drop row 2."""
        text = _make_table(_row(1), "", _row(2))
        tested, total = _parse_ledger(text)
        assert total == 2, (
            f"Expected 2 rows, got {total}. "
            "Blank line between rows caused the parser to exit the table early."
        )
        assert tested == 2

    def test_multiple_blank_lines_between_rows(self):
        text = _make_table(_row(1), "", "", _row(2), "", _row(3))
        assert _parse_ledger(text) == (3, 3)

    def test_blank_line_before_first_row(self):
        """Blank line immediately after separator row."""
        header = "| # | ERP File | Date | Touch | Raised | Contract Tests | PR |"
        sep    = "|---|---|---|---|---|---|---|"
        text   = f"{header}\n{sep}\n\n{_row(1)}\n"
        tested, total = _parse_ledger(text)
        assert total == 1

    def test_row_after_trailing_blank_lines_counted(self):
        """Row 6 scenario from Sprint 9: was after the --- + blank separator."""
        rows = [_row(i) for i in range(1, 6)]
        text = _make_table(*rows, "", _row(6))
        assert _parse_ledger(text) == (6, 6)


# ---------------------------------------------------------------------------
# Pipe character inside a cell must not break column counting
# ---------------------------------------------------------------------------

class TestPipeInsideCell:
    def test_pipe_in_touch_column_does_not_break_contract_tests(self):
        r"""A cell containing '\|' (Markdown pipe escape) must not shift column index."""
        row = "| 1 | backend/routes/invoices.py | 2026-07 | Read \\| Write | DONE | ✅ | PR#1 |"
        text = _make_table(row)
        tested, total = _parse_ledger(text)
        assert total == 1
        assert tested == 1


# ---------------------------------------------------------------------------
# Heading stops the table (correct behaviour)
# ---------------------------------------------------------------------------

class TestHeadingStopsTable:
    def test_heading_after_rows_stops_counting(self):
        """A Markdown heading ends the table — rows after it are not data rows."""
        header = "| # | ERP File | Date | Touch | Raised | Contract Tests | PR |"
        sep    = "|---|---|---|---|---|---|---|"
        text   = f"{header}\n{sep}\n{_row(1)}\n{_row(2)}\n\n## Pending Rows\n{_row(3)}\n"
        tested, total = _parse_ledger(text)
        # Row 3 is under "Pending Rows" — should not be counted
        assert total == 2

    def test_pending_rows_sentinel_stops_counting(self):
        text = _make_table(_row(1), _row(2), pending=True) + _row(3) + "\n"
        tested, total = _parse_ledger(text)
        assert total == 2
