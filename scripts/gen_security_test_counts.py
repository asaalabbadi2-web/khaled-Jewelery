#!/usr/bin/env python3
"""Generate the security test count table for docs/security/security-overview.md §11.

Usage:
    python scripts/gen_security_test_counts.py

Outputs the Markdown table for §11 (Test Inventory) with live counts from pytest
--collect-only. Run before committing a change that adds or removes security tests.

The total line at the bottom of §11 can then be pasted into security-overview.md,
replacing the hand-maintained numbers.
"""
from __future__ import annotations

import subprocess
import sys
from collections import defaultdict
from pathlib import Path


# Which test files map to which law and description.
# Adjust if files are renamed or new laws are added.
_FILES: list[tuple[str, str, str]] = [
    (
        "apps/commerce-api/tests/security/test_route_security_scan.py",
        "Law 1 (scope scan)",
        "Every route has a scope entry; missing entry fails CI",
    ),
    (
        "apps/commerce-api/tests/security/test_log_redaction.py",
        "Law 2 (redaction)",
        "Message · args · tracebacks; non-sensitive fields pass",
    ),
    (
        "apps/commerce-api/tests/security/test_route_security_scan.py",
        "Law 3 (rate class scan)",
        "Every route has a rate class; missing entry fails CI",
    ),
    (
        "apps/commerce-api/tests/security/test_rate_limiting.py",
        "Law 3 (enforcement)",
        "Fixed-window · XFF forge · webhook isolation · production config",
    ),
    (
        "apps/commerce-api/tests/security/test_jwt_auth.py",
        "Law 4 JWT unit",
        "Valid/expired/wrong-secret/missing-claims/scope distinction",
    ),
    (
        "apps/commerce-api/tests/security/test_admin_scope_enforcement.py",
        "Law 4 admin-side",
        "Customer JWT → 403 on all admin endpoints",
    ),
    (
        "apps/commerce-api/tests/security/test_law4_customer_scope.py",
        "Law 4 customer-side",
        "No JWT → 401; customer JWT → passes; admin JWT → passes; count scan",
    ),
    (
        "packages/domain/tests/reservation/test_bola.py",
        "Law 5 BOLA (domain)",
        "Ownership in service layer; None → 404; customer_ref=None denied",
    ),
    (
        "apps/commerce-api/tests/security/test_payment_bola.py",
        "Law 5 BOLA (API)",
        "Payment respects reservation ownership",
    ),
    (
        "apps/commerce-api/tests/security/test_webhook_signature.py",
        "Law 6 (sig before domain)",
        "Forged payload does not reach domain service",
    ),
    (
        "apps/commerce-api/tests/security/test_open_surfaces.py",
        "Open surfaces (xfail witnesses)",
        "Known gaps — XPASS = gap closed without updating docs",
    ),
]


def _collect_count(abs_path: str, repo_root: Path) -> int:
    """Run pytest --collect-only on abs_path and count test IDs."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", abs_path, "--collect-only", "-q", "--tb=no"],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
    )
    lines = [
        line for line in result.stdout.splitlines()
        if "::" in line and not line.startswith(" ")
    ]
    return len(lines)


def main() -> None:
    repo_root = Path(__file__).parent.parent

    rows: list[tuple[str, str, int, str]] = []
    seen_files: dict[str, int] = {}
    total = 0

    # Count each unique file once
    unique_paths = list(dict.fromkeys(path for path, _, _ in _FILES))
    unique_counts: dict[str, int] = {}
    for path in unique_paths:
        unique_counts[path] = _collect_count(str(repo_root / path), repo_root)

    for path, law, description in _FILES:
        count = unique_counts[path]
        rows.append((law, path.split("/")[-1], count, description))

    dedup_total = sum(unique_counts.values())
    seen = set(unique_paths)

    print("| Law | Test file | Tests | What it proves |")
    print("|-----|-----------|-------|----------------|")
    for law, filename, count, description in rows:
        print(f"| {law} | `{filename}` | {count} | {description} |")
    print()
    print(f"**Total: {dedup_total} security tests across {len(seen)} files.**")
    print()
    print(
        "Note: `test_route_security_scan.py` covers both Law 1 and Law 3 scans; "
        "counted once in the total."
    )


if __name__ == "__main__":
    main()
