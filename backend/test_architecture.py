"""Architectural boundary tests — enforced via AST, no DB required.

These tests run without any database connection and catch boundary violations
in CI before any runtime test executes.

RULE-1  Single Writer
    Only InventoryPostingService may instantiate InventoryLedger.
    Any other file that calls InventoryLedger(...) bypasses the Single Writer.

RULE-2  No Direct Balance Writes
    Only InventoryPostingService may instantiate InventoryBalance.
    All other code must read via .query; writes go through _apply_to_balance().

RULE-3  GL Boundary
    Inventory services (posting, count, adjustment) must not import
    JournalEntry or JournalEntryLine directly.
    GL creation is the responsibility of InventoryAccountingService alone.

RULE-4  Acyclic Service Dependencies
    The import graph of services/inventory_*.py must be a DAG.
    Circular imports produce unpredictable load order and hide design flaws.

How to add a new rule:
    1. Write a helper function that scans AST or text.
    2. Add a test method to the appropriate class.
    3. Add an ADR entry explaining the boundary if it is non-obvious.
"""
from __future__ import annotations

import ast
import pathlib
from typing import Dict, Set

import pytest

BACKEND_DIR  = pathlib.Path(__file__).parent
SERVICES_DIR = BACKEND_DIR / 'services'

# ── Configuration ─────────────────────────────────────────────────────────────

# Files allowed to instantiate InventoryLedger
ALLOWED_LEDGER_WRITERS: set[str] = {'inventory_posting_service.py'}
# Files allowed to instantiate InventoryBalance
ALLOWED_BALANCE_WRITERS: set[str] = {'inventory_posting_service.py'}

# Patterns whose presence in a filename means "skip this file"
_SKIP_PATTERNS = (
    'test_', 'conftest', 'alembic', '__pycache__',
    'fix_', 'backfill_', 'inspect_', 'diagnose_', 'check_',
    'seed_', 'add_', 'init_', 'manual_', 'repair_',
    'update_', 'debug_', 'migrate_', 'import_',
)
# Directory names that are excluded entirely (migration scripts, one-off tools)
_SKIP_DIRS = ('migration_v2', 'migrations', 'alembic')


# ── Helpers ───────────────────────────────────────────────────────────────────

def _scannable_files() -> list[pathlib.Path]:
    """All backend .py files minus tests, migrations, and one-off scripts."""
    result = []
    for p in BACKEND_DIR.rglob('*.py'):
        if any(d in p.parts for d in _SKIP_DIRS):
            continue
        if '__pycache__' in p.parts:
            continue
        if any(pat in p.name for pat in _SKIP_PATTERNS):
            continue
        result.append(p)
    return result


def _parse(filepath: pathlib.Path):
    try:
        return ast.parse(filepath.read_text(encoding='utf-8'))
    except (SyntaxError, UnicodeDecodeError):
        return None


def _instantiates(filepath: pathlib.Path, class_name: str) -> bool:
    """True if filepath contains `class_name(...)` — a constructor call.

    Matches both `InventoryLedger(...)` and `models.InventoryLedger(...)`.
    Does NOT match `.query`, `.filter_by`, or class definitions.
    """
    tree = _parse(filepath)
    if tree is None:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == class_name:
            return True
        if isinstance(func, ast.Attribute) and func.attr == class_name:
            return True
    return False


def _imports_name(filepath: pathlib.Path, *names: str) -> list[str]:
    """Return names that are imported in filepath."""
    tree = _parse(filepath)
    if tree is None:
        return []
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in names:
                    found.append(alias.name)
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in names:
                    found.append(alias.name)
    return found


def _service_deps(filepath: pathlib.Path) -> Set[str]:
    """Return service module stems imported by filepath.

    e.g. 'from services.inventory_posting_service import ...' → {'inventory_posting_service'}
    """
    tree = _parse(filepath)
    if tree is None:
        return set()
    deps: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if 'services.' in node.module:
                stem = node.module.split('.')[-1]
                deps.add(stem)
    return deps


def _has_cycle(graph: Dict[str, Set[str]]) -> list[str]:
    """Return nodes involved in cycles (empty = acyclic)."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}
    cycle_nodes: list[str] = []

    def dfs(node: str) -> bool:
        color[node] = GRAY
        for nb in graph.get(node, set()):
            if nb not in color:
                continue
            if color[nb] == GRAY:
                cycle_nodes.append(node)
                return True
            if color[nb] == WHITE and dfs(nb):
                return True
        color[node] = BLACK
        return False

    for n in list(graph):
        if color[n] == WHITE:
            dfs(n)
    return cycle_nodes


# ── RULE-1: Single Writer ─────────────────────────────────────────────────────

class TestSingleWriter:
    """Only InventoryPostingService may instantiate inventory event-log classes.

    See ADR-001 (single-writer) and ADR-002 (append-only ledger).
    """

    def test_only_posting_service_creates_inventory_ledger_rows(self):
        violators = [
            str(p.relative_to(BACKEND_DIR))
            for p in _scannable_files()
            if p.name not in ALLOWED_LEDGER_WRITERS
            if _instantiates(p, 'InventoryLedger')
        ]
        assert violators == [], (
            'RULE-1: InventoryLedger instantiated outside InventoryPostingService:\n'
            + '\n'.join(f'  {v}' for v in violators)
            + '\nAll inventory movements must go through '
              'InventoryPostingService.post(). See ADR-001.'
        )

    def test_only_posting_service_creates_inventory_balance_rows(self):
        violators = [
            str(p.relative_to(BACKEND_DIR))
            for p in _scannable_files()
            if p.name not in ALLOWED_BALANCE_WRITERS
            if _instantiates(p, 'InventoryBalance')
        ]
        assert violators == [], (
            'RULE-1: InventoryBalance instantiated outside InventoryPostingService:\n'
            + '\n'.join(f'  {v}' for v in violators)
            + '\nBalance rows are managed by '
              'InventoryPostingService._apply_to_balance(). See ADR-003.'
        )


# ── RULE-3: GL Boundary ───────────────────────────────────────────────────────

class TestGLBoundary:
    """Inventory services must not import GL types directly.

    GL creation belongs exclusively in InventoryAccountingService.
    See ADR-005.
    """

    _GL_TYPES = ('JournalEntry', 'JournalEntryLine')
    _PROTECTED_SERVICES = (
        'inventory_posting_service.py',
        'inventory_count_service.py',
        'inventory_adjustment_service.py',
        'inventory_invariant_checker.py',
        'inventory_reconciliation_report.py',
        'inventory_health_report.py',
    )

    def test_inventory_services_do_not_import_journal_entry(self):
        violators = []
        for svc_name in self._PROTECTED_SERVICES:
            p = SERVICES_DIR / svc_name
            if not p.exists():
                continue
            found = _imports_name(p, *self._GL_TYPES)
            for name in found:
                violators.append(f'{svc_name} → {name}')

        assert violators == [], (
            'RULE-3: Inventory services import GL types directly:\n'
            + '\n'.join(f'  {v}' for v in violators)
            + '\nGL creation belongs in InventoryAccountingService. See ADR-005.'
        )


# ── RULE-4: Acyclic Service Dependencies ──────────────────────────────────────

class TestAcyclicDependencies:
    """The import graph of inventory services must be a directed acyclic graph.

    A cycle means A→B→A, which indicates a design problem.
    Expected dependency order (high → low):
        inventory_count_service
        inventory_adjustment_service
        inventory_accounting_service
        inventory_posting_service       ← lowest level; imports nothing upward
        inventory_invariant_checker
        inventory_reconciliation_report
        inventory_health_report
    """

    def test_inventory_services_import_graph_is_acyclic(self):
        service_files = list(SERVICES_DIR.glob('inventory_*.py'))
        if not service_files:
            pytest.skip('No inventory service files found')

        graph: Dict[str, Set[str]] = {}
        for p in service_files:
            stem = p.stem
            graph[stem] = _service_deps(p) & {f.stem for f in service_files}

        cycles = _has_cycle(graph)
        assert cycles == [], (
            f'RULE-4: Circular dependency detected in inventory services: {cycles}\n'
            f'Dependency graph: '
            + str({k: sorted(v) for k, v in graph.items() if v})
        )

    def test_posting_service_does_not_import_higher_level_services(self):
        """InventoryPostingService is the lowest-level writer.

        It must not import count, adjustment, or accounting services —
        those depend on it, not the other way around.
        """
        p = SERVICES_DIR / 'inventory_posting_service.py'
        if not p.exists():
            pytest.skip('inventory_posting_service.py not found')

        forbidden_imports = {
            'inventory_count_service',
            'inventory_adjustment_service',
            'inventory_accounting_service',
        }
        deps = _service_deps(p)
        violations = deps & forbidden_imports
        assert not violations, (
            f'RULE-4: InventoryPostingService imports higher-level services: {violations}\n'
            'This creates an upward dependency. Restructure to remove the cycle.'
        )
