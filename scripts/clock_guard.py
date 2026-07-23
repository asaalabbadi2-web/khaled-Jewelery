#!/usr/bin/env python3
"""clock_guard.py — Enforce Clock Discipline in decision-path modules.

Detects bare datetime.now() / datetime.utcnow() calls in decision-path
directories. Such calls must be replaced with the injected Clock Provider
per ADR-015 §Clock Discipline.

Decision-path directories scanned:
    packages/domain/src/
    apps/commerce-api/src/yasargold_commerce/workers/
    backend/services/

─── Suppression comment taxonomy ────────────────────────────────────────────
  # clock-guard: boundary      Correct ADR-015 boundary call — worker/router
                                calls datetime.now() once and passes it down.
                                NOT counted as debt; exempt from the ratchet.

  # clock-guard: TIME-001      Known Gap — legacy wall-clock call in decision
                                code. Counted against the baseline ratchet in
                                docs/architecture/.clock-debt-baseline. This
                                count may only DECREASE. Adding a new TIME-001
                                suppression fails CI.

  # clock-guard: record-only   Pure audit/display timestamp; no decision path
                                reads this value to change state. Not debt.

─── Ratchet ─────────────────────────────────────────────────────────────────
  The baseline (docs/architecture/.clock-debt-baseline) stores the committed
  count of TIME-001 suppressions. CI fails if the current count EXCEEDS the
  baseline (new debt added). The count may only stay equal or shrink.

  To lower the baseline after genuinely removing suppressions:
      python scripts/clock_guard.py --update
  This flag is only accepted in the same PR that removes suppressions.
  Never run --update standalone to "forgive" new debt — it will fail on the
  next run if violations remain.

─── Exit codes ───────────────────────────────────────────────────────────────
  0 — no violations found, ratchet passed
  1 — unacknowledged violation found, OR ratchet exceeded
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent

DECISION_PATHS: list[Path] = [
    REPO_ROOT / "packages" / "domain" / "src",
    REPO_ROOT / "apps" / "commerce-api" / "src" / "yasargold_commerce" / "workers",
    REPO_ROOT / "backend" / "services",
]

BASELINE_FILE = REPO_ROOT / "docs" / "architecture" / ".clock-debt-baseline"

# Matches any bare call to the host clock
_CLOCK_RE = re.compile(r"datetime\.(?:now|utcnow)\(")

# Matches a TIME-001 suppression (the only kind counted against the baseline)
_TIME001_RE = re.compile(r"#\s*clock-guard:\s*TIME-001")

# Lines matching any of these patterns are NOT violations:
#   1. Clock-factory function body  → return datetime.now(
#   2. ADR-015 injection fallback   → <var> or datetime.now(
#   3. Any suppression comment      → # clock-guard: <tag>
_SAFE_PATTERNS: list[re.Pattern] = [
    re.compile(r"^\s*return\s+datetime\.(?:now|utcnow)\("),
    re.compile(r"\bor\s+datetime\.(?:now|utcnow)\("),
    re.compile(r"#\s*clock-guard:"),
]


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _is_test_file(path: Path) -> bool:
    parts = path.parts
    return (
        "tests" in parts
        or path.name.startswith("test_")
        or path.name.endswith("_test.py")
        or path.name == "testing.py"   # domain test-fixture builders (not decision code)
    )


def _scan_file(path: Path) -> list[tuple[int, str]]:
    """Return (lineno, line) for every unacknowledged bare clock call in path."""
    violations: list[tuple[int, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return violations

    for lineno, line in enumerate(text.splitlines(), 1):
        if not _CLOCK_RE.search(line):
            continue
        if any(pat.search(line) for pat in _SAFE_PATTERNS):
            continue
        violations.append((lineno, line.rstrip()))

    return violations


def _count_time001_suppressions() -> int:
    """Count # clock-guard: TIME-001 suppression lines across all decision paths.

    boundary and record-only suppressions are NOT counted — they are correct
    by definition and exempt from the debt ratchet.
    """
    count = 0
    for base in DECISION_PATHS:
        if not base.exists():
            continue
        for py_file in base.rglob("*.py"):
            if _is_test_file(py_file):
                continue
            try:
                text = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for line in text.splitlines():
                if _TIME001_RE.search(line):
                    count += 1
    return count


def _read_baseline() -> int | None:
    if not BASELINE_FILE.exists():
        return None
    try:
        return int(BASELINE_FILE.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def _write_baseline(count: int) -> None:
    BASELINE_FILE.write_text(str(count) + "\n", encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> int:
    update_mode = "--update" in sys.argv

    # ── Phase 1: violation scan ──────────────────────────────────────────────
    found_any = False
    for base in DECISION_PATHS:
        if not base.exists():
            continue
        for py_file in sorted(base.rglob("*.py")):
            if _is_test_file(py_file):
                continue
            violations = _scan_file(py_file)
            for lineno, line in violations:
                rel = py_file.relative_to(REPO_ROOT)
                print(f"{rel}:{lineno}  Use injected Clock instead  →  {line.strip()}")
                found_any = True

    if found_any:
        print()
        print("clock_guard: FAIL — bare datetime.now() in decision-path code.")
        print("  Fix A: inject `now: datetime` as a parameter (preferred).")
        print("  Fix B: if this is a Known Gap, add `# clock-guard: TIME-001` and")
        print("         register the violation in docs/architecture/architecture-v1.md §4.6.")
        return 1

    # ── Phase 2: ratchet ────────────────────────────────────────────────────
    current_count = _count_time001_suppressions()

    if update_mode:
        _write_baseline(current_count)
        print(f"clock_guard: baseline updated → {current_count} TIME-001 suppressions.")
        print(f"  File: {BASELINE_FILE.relative_to(REPO_ROOT)}")
        print("  Rule: only commit this update in the same PR that removes suppressions.")
        return 0

    baseline = _read_baseline()
    if baseline is None:
        print("clock_guard: PASS — no violations found (no baseline file; run --update to initialise).")
        return 0

    if current_count > baseline:
        print()
        print(f"clock_guard: RATCHET FAIL — TIME-001 debt increased ({current_count} > {baseline} baseline).")
        print("  A new `# clock-guard: TIME-001` suppression was added.")
        print("  Inject the Clock Provider instead of suppressing (ADR-015).")
        print("  The baseline may only DECREASE. Use boundary or record-only tags for legitimate cases.")
        return 1

    if current_count < baseline:
        print(f"clock_guard: PASS — {current_count} TIME-001 suppressions ({baseline - current_count} below baseline).")
        print(f"  Debt reduced! Run 'python scripts/clock_guard.py --update' to lower the baseline.")
    else:
        print(f"clock_guard: PASS — {current_count} TIME-001 suppressions (at baseline).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
