#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

MAX_DELETED_LINES = int(os.getenv('QUALITY_GUARD_MAX_DELETED_LINES', '1500'))
MAX_DELETION_RATIO = float(os.getenv('QUALITY_GUARD_MAX_DELETION_RATIO', '0.60'))
MIN_CHANGESET_FOR_RATIO = int(os.getenv('QUALITY_GUARD_MIN_CHANGESET_FOR_RATIO', '120'))
MIN_BACKEND_COVERAGE = float(os.getenv('QUALITY_GUARD_MIN_BACKEND_COVERAGE', '15'))

BACKEND_SENSITIVE = [
    re.compile(r'^backend/.*\.py$'),
    re.compile(r'^backend/requirements\.txt$'),
]
FRONTEND_SENSITIVE = [
    re.compile(r'^frontend/lib/.*\.dart$'),
    re.compile(r'^frontend/pubspec\.yaml$'),
]

@dataclass(frozen=True)
class DiffEntry:
    additions: int
    deletions: int
    path: str


def run_git(args: list[str]) -> str:
    completed = subprocess.run(
        ['git', '-C', str(ROOT), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout


def parse_numstat(output: str) -> list[DiffEntry]:
    entries: list[DiffEntry] = []
    for raw_line in output.splitlines():
        if not raw_line.strip():
            continue
        parts = raw_line.split('\t')
        if len(parts) < 3:
            continue
        additions_raw, deletions_raw, path = parts[0], parts[1], '\t'.join(parts[2:])
        try:
            additions = int(additions_raw)
        except ValueError:
            additions = 0
        try:
            deletions = int(deletions_raw)
        except ValueError:
            deletions = 0
        entries.append(DiffEntry(additions=additions, deletions=deletions, path=path))
    return entries


def changed_files(*, staged: bool, base: str | None, head: str | None) -> list[DiffEntry]:
    if staged:
        output = run_git(['diff', '--cached', '--numstat', '--no-renames', '--'])
    else:
        if not base or not head:
            raise SystemExit('base/head are required unless --staged is set')
        output = run_git(['diff', '--numstat', '--no-renames', base, head, '--'])
    return parse_numstat(output)


def matches_any(path: str, patterns: list[re.Pattern[str]]) -> bool:
    return any(pattern.match(path) for pattern in patterns)


def classify(entries: list[DiffEntry]) -> dict[str, list[DiffEntry]]:
    buckets = {
        'backend_sensitive': [],
        'frontend_sensitive': [],
        'other': [],
    }
    for entry in entries:
        if matches_any(entry.path, BACKEND_SENSITIVE):
            buckets['backend_sensitive'].append(entry)
        elif matches_any(entry.path, FRONTEND_SENSITIVE):
            buckets['frontend_sensitive'].append(entry)
        else:
            buckets['other'].append(entry)
    return buckets


def print_summary(entries: list[DiffEntry]) -> None:
    additions = sum(item.additions for item in entries)
    deletions = sum(item.deletions for item in entries)
    total = additions + deletions
    ratio = (deletions / total * 100.0) if total else 0.0
    print(f'changed_files={len(entries)} additions={additions} deletions={deletions} deletion_ratio={ratio:.1f}%')


def fail(message: str) -> None:
    print(f'QUALITY GUARD FAILED: {message}', file=sys.stderr)
    raise SystemExit(1)


def run_command(command: list[str], cwd: Path, label: str) -> None:
    print(f'[guard] {label}: {" ".join(command)}')
    completed = subprocess.run(command, cwd=str(cwd), text=True)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def local_python() -> list[str]:
    candidates = [
        ROOT / 'backend' / 'venv' / 'bin' / 'python',
        ROOT / '.venv' / 'bin' / 'python',
        Path(sys.executable),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return [str(candidate)]
    return ['python3']


def has_module(python_cmd: list[str], module: str) -> bool:
    completed = subprocess.run(
        [*python_cmd, '-c', f'import importlib.util; raise SystemExit(0 if importlib.util.find_spec({module!r}) else 1)'],
        cwd=str(ROOT),
    )
    return completed.returncode == 0


def backend_test_command() -> list[str]:
    python_cmd = local_python()
    if has_module(python_cmd, 'coverage'):
        return [*python_cmd, '-m', 'coverage', 'run', '-m', 'pytest', '-q']
    return [*python_cmd, '-m', 'pytest', '-q']


def backend_coverage_report_command() -> list[str] | None:
    python_cmd = local_python()
    if has_module(python_cmd, 'coverage'):
        return [*python_cmd, '-m', 'coverage', 'report', f'--fail-under={MIN_BACKEND_COVERAGE}']
    return None


def flutter_available() -> bool:
    return subprocess.run(['flutter', '--version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def run_backend_checks() -> None:
    if not (ROOT / 'backend').exists():
        fail('backend folder is missing')
    run_command(backend_test_command(), ROOT / 'backend', 'backend tests')
    report_command = backend_coverage_report_command()
    if report_command:
        run_command(report_command, ROOT / 'backend', 'backend coverage report')
    else:
        fail('coverage is not installed in the active Python environment; install backend requirements first')


def run_frontend_checks() -> None:
    if not flutter_available():
        fail('flutter is not available on PATH')
    run_command(['flutter', 'analyze'], ROOT / 'frontend', 'flutter analyze')
    run_command(['flutter', 'test'], ROOT / 'frontend', 'flutter test')


def main() -> int:
    parser = argparse.ArgumentParser(description='Guard against large deletions and untested sensitive changes')
    parser.add_argument('--staged', action='store_true', help='inspect staged changes instead of a base/head range')
    parser.add_argument('--base', help='base git revision for diff inspection')
    parser.add_argument('--head', help='head git revision for diff inspection')
    parser.add_argument('--run-tests', action='store_true', help='run backend/frontend test commands when relevant')
    args = parser.parse_args()

    entries = changed_files(staged=args.staged, base=args.base, head=args.head)
    if not entries:
        print('QUALITY GUARD: no changed files detected')
        return 0

    print_summary(entries)
    buckets = classify(entries)

    additions = sum(item.additions for item in entries)
    deletions = sum(item.deletions for item in entries)
    total = additions + deletions
    if deletions >= MAX_DELETED_LINES:
        fail(f'deleted lines {deletions} exceed limit {MAX_DELETED_LINES}')
    if total >= MIN_CHANGESET_FOR_RATIO and total > 0 and (deletions / total) >= MAX_DELETION_RATIO and deletions >= 100:
        fail(f'deletion ratio {deletions / total:.2%} is too high for a {total}-line change set')

    if args.run_tests:
        if buckets['backend_sensitive']:
            run_backend_checks()
        if buckets['frontend_sensitive']:
            run_frontend_checks()

    print('QUALITY GUARD PASSED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())