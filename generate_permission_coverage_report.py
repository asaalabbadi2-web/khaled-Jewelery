#!/usr/bin/env python3
"""Generate a permission coverage report for backend/routes.py.

This script is intentionally import-free (does not import backend as a package)
so it can run even if the backend package has environment-specific import paths.

It parses:
- backend/permissions.py: builds the set of permission codes from *_PERMISSIONS dicts
- backend/routes.py: extracts @api.route decorators + HTTP methods

Then it applies the same conservative inference rules currently implemented in
backend/routes.py::_infer_permission_code and reports any endpoints that cannot
be mapped to a known permission in the catalog.
"""

from __future__ import annotations

import ast
import datetime as _dt
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent
PERMISSIONS_PY = ROOT / "backend" / "permissions.py"
ROUTES_PY = ROOT / "backend" / "routes.py"
REPORT_MD = ROOT / "PERMISSIONS_ENDPOINT_COVERAGE_REPORT.md"


@dataclass(frozen=True)
class RouteEntry:
    blueprint: str
    path: str
    methods: tuple[str, ...]
    func_name: str
    lineno: int
    explicit_required_permissions: tuple[str, ...]


def _safe_literal(node: ast.AST):
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def _extract_permission_catalog_keys(permissions_py: Path) -> set[str]:
    """Extract permission codes from *_PERMISSIONS dict literals.

    We intentionally avoid importing backend.permissions.
    """
    tree = ast.parse(permissions_py.read_text(encoding="utf-8"), filename=str(permissions_py))

    perm_dict_names: set[str] = set()
    assignments: dict[str, ast.AST] = {}

    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            assignments[name] = node.value
            if name.endswith("_PERMISSIONS") and name != "ROLE_PERMISSIONS" and name != "ALL_PERMISSIONS":
                perm_dict_names.add(name)

    keys: set[str] = set()
    for name in sorted(perm_dict_names):
        val = assignments.get(name)
        if isinstance(val, ast.Dict):
            for k in val.keys:
                lit = _safe_literal(k)
                if isinstance(lit, str):
                    keys.add(lit)

    return keys


def _extract_api_routes(routes_py: Path, blueprint_name: str = "api") -> list[RouteEntry]:
    tree = ast.parse(routes_py.read_text(encoding="utf-8"), filename=str(routes_py))

    routes: list[RouteEntry] = []

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        func_name = node.name
        lineno = getattr(node, "lineno", 0) or 0

        # Collect any explicit require_permission('code') decorators
        explicit_perms: list[str] = []
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name) and dec.func.id == "require_permission":
                if dec.args:
                    lit = _safe_literal(dec.args[0])
                    if isinstance(lit, str):
                        explicit_perms.append(lit)

        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            func = dec.func
            if not (isinstance(func, ast.Attribute) and func.attr == "route"):
                continue
            if not (isinstance(func.value, ast.Name) and func.value.id == blueprint_name):
                continue

            # First positional arg is the path
            if not dec.args:
                continue
            path_lit = _safe_literal(dec.args[0])
            if not isinstance(path_lit, str):
                continue

            methods: list[str] = []
            for kw in dec.keywords or []:
                if kw.arg == "methods":
                    val = _safe_literal(kw.value)
                    if isinstance(val, (list, tuple)):
                        methods = [str(m).upper() for m in val]
            if not methods:
                methods = ["GET"]

            routes.append(
                RouteEntry(
                    blueprint=blueprint_name,
                    path=path_lit,
                    methods=tuple(methods),
                    func_name=func_name,
                    lineno=lineno,
                    explicit_required_permissions=tuple(explicit_perms),
                )
            )

    return routes


def _infer_permission_code(path: str, method: str, all_permissions: set[str]) -> str | None:
    """Mirror backend/routes.py::_infer_permission_code (conservative)."""
    permission_resource_map = {
        # system
        "settings": "system.settings",
        "system": "system",

        # business entities
        "customers": "customers",
        "suppliers": "suppliers",
        "items": "items",
        "invoices": "invoices",
        "employees": "employees",
        "accounts": "accounts",
        "gold_price": "gold_price",
        "gold-price": "gold_price",

        # accounting
        "journal_entries": "journal",
        "journal-entries": "journal",
        "vouchers": "vouchers",
    }

    segments = [s for s in (path or "").strip("/").split("/") if s]
    if segments and segments[0] == "api":
        segments = segments[1:]
    if not segments:
        return None

    resource = segments[0]
    remainder = segments[1:]

    mapped = permission_resource_map.get(resource)
    if mapped == "system.settings":
        return "system.settings" if "system.settings" in all_permissions else None

    action = None
    m = (method or "").upper()
    last = remainder[-1] if remainder else ""

    if resource in ("journal_entries", "journal-entries"):
        if m == "GET":
            action = "view"
        elif m == "POST":
            if last in ("soft_delete", "delete"):
                action = "delete"
            elif last == "restore":
                action = "edit"
            else:
                action = "create"
        elif m in ("PUT", "PATCH"):
            action = "edit"
        elif m == "DELETE":
            action = "delete"

        code = f"journal.{action}"
        return code if code in all_permissions else None

    if resource in ("gold_price", "gold-price"):
        action = "view" if m == "GET" else "update"
        code = f"gold_price.{action}"
        return code if code in all_permissions else None

    module = mapped or resource
    if module == "system":
        code = "system.settings"
        return code if code in all_permissions else None

    if m == "GET":
        action = "view"
    elif m == "POST":
        if last in ("soft_delete", "delete"):
            action = "delete"
        elif last in ("restore", "adjust", "toggle-active", "toggle_active"):
            action = "edit"
        else:
            action = "create"
    elif m in ("PUT", "PATCH"):
        action = "edit"
    elif m == "DELETE":
        action = "delete"

    if action is None:
        return None

    candidate = f"{module}.{action}"
    if candidate in all_permissions:
        return candidate

    if module.endswith("s"):
        singular = module[:-1]
        candidate2 = f"{singular}.{action}"
        if candidate2 in all_permissions:
            return candidate2

    return None


def _group_key_for_path(path: str) -> str:
    segs = [s for s in (path or "").strip("/").split("/") if s]
    if segs and segs[0] == "api":
        segs = segs[1:]
    return segs[0] if segs else "(root)"


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|")


def main() -> int:
    if not PERMISSIONS_PY.exists():
        raise SystemExit(f"Missing: {PERMISSIONS_PY}")
    if not ROUTES_PY.exists():
        raise SystemExit(f"Missing: {ROUTES_PY}")

    permission_keys = _extract_permission_catalog_keys(PERMISSIONS_PY)
    routes = _extract_api_routes(ROUTES_PY, blueprint_name="api")

    covered: list[tuple[RouteEntry, str]] = []
    unknown: list[RouteEntry] = []
    explicit_missing_in_catalog: list[tuple[RouteEntry, str]] = []

    # Track coverage on a per-(method,path) basis.
    # If an endpoint has an explicit @require_permission that exists in the catalog,
    # we treat all its declared methods as covered.
    covered_method_entries: set[tuple[str, str, str]] = set()  # (METHOD, PATH, CODE)
    unknown_method_entries: set[tuple[str, str, str, int]] = set()  # (METHOD, PATH, FUNC, LINE)

    for r in routes:
        # Check explicit decorators first (if present)
        if r.explicit_required_permissions:
            for code in r.explicit_required_permissions:
                if code not in permission_keys:
                    explicit_missing_in_catalog.append((r, code))

        explicit_in_catalog = [c for c in r.explicit_required_permissions if c in permission_keys]

        any_unknown = False
        for method in r.methods:
            # Explicit decorator coverage takes precedence over inference.
            if explicit_in_catalog:
                # In practice this is typically a single permission code.
                for code in explicit_in_catalog:
                    covered_method_entries.add((method.upper(), r.path, code))
                    covered.append((r, code))
                continue

            perm = _infer_permission_code(r.path, method, permission_keys)
            if perm is None:
                any_unknown = True
                unknown_method_entries.add((method.upper(), r.path, r.func_name, r.lineno))
            else:
                covered_method_entries.add((method.upper(), r.path, perm))
                covered.append((r, perm))
        if any_unknown:
            unknown.append(r)

    # Normalize method case and de-duplicate counts based on (method+path).
    covered_set = {(m.upper(), p, code) for (m, p, code) in covered_method_entries}
    unknown_methods = {(m.upper(), p, fn, ln) for (m, p, fn, ln) in unknown_method_entries}

    # Group unknown by top-level resource
    by_resource: dict[str, list[tuple[str, str, str, int]]] = {}
    for m, p, fn, ln in sorted(unknown_methods):
        key = _group_key_for_path(p)
        by_resource.setdefault(key, []).append((m, p, fn, ln))

    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines: list[str] = []
    lines.append(f"# Permissions Endpoint Coverage Report\n")
    lines.append(f"Generated: {now}\n")
    lines.append("This report checks only endpoints defined in `backend/routes.py` under the `api` blueprint.\n")
    lines.append("Coverage rules (static analysis):\n")
    lines.append("- If an endpoint has an explicit `@require_permission('code')` decorator and `code` exists in the catalog, it is considered **covered**.\n")
    lines.append("- Otherwise, we fall back to the conservative inference logic mirrored from `backend/routes.py::_infer_permission_code`.\n")
    lines.append("- If neither explicit coverage nor inference yields a catalog permission, it is listed as **unknown / uncovered**.\n")

    lines.append("## Summary\n")
    lines.append("| Metric | Value |\n")
    lines.append("|---|---:|\n")
    lines.append(f"| Permission codes in catalog (from `*_PERMISSIONS`) | {len(permission_keys)} |\n")
    lines.append(f"| @api.route endpoints in `backend/routes.py` | {len(routes)} |\n")
    lines.append(f"| Covered method entries (method+path) | {len(covered_set)} |\n")
    lines.append(f"| Unknown method entries (method+path) | {len(unknown_methods)} |\n")
    lines.append(f"| Unknown resource groups | {len(by_resource)} |\n")

    if explicit_missing_in_catalog:
        lines.append("\n## Explicit permission decorators not in catalog\n")
        lines.append("Some endpoints use `@require_permission('...')` but the referenced code is not present in `backend/permissions.py` catalog dicts.\n")
        lines.append("| Function | Line | Path | Code |\n")
        lines.append("|---|---:|---|---|\n")
        for r, code in sorted(explicit_missing_in_catalog, key=lambda x: (x[0].lineno, x[1])):
            lines.append(
                f"| `{_md_escape(r.func_name)}` | {r.lineno} | `{_md_escape(r.path)}` | `{_md_escape(code)}` |\n"
            )

    lines.append("\n## Unknown / Uncovered endpoints\n")
    lines.append("These endpoints currently do **not** map to any permission in the catalog under the current inference rules.\n")
    lines.append("Most common reasons:\n")
    lines.append("- The endpoint is for a resource not in `_PERMISSION_RESOURCE_MAP`\n")
    lines.append("- It is an action endpoint (eg. `/post`, `/approve`, `/cancel`, `/backup`) not mapped to `*.edit`/`*.delete`/etc\n")
    lines.append("- The catalog has a permission (eg. `journal.post`) but inference does not return it\n")

    for resource, items in sorted(by_resource.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        lines.append(f"\n### {resource} ({len(items)})\n")
        lines.append("| Method | Path | Function | Line |\n")
        lines.append("|---|---|---|---:|\n")
        for m, p, fn, ln in items:
            lines.append(f"| {m} | `{_md_escape(p)}` | `{_md_escape(fn)}` | {ln} |\n")

    lines.append("\n## Notes\n")
    lines.append("- If `BYPASS_AUTH_FOR_DEVELOPMENT` is enabled, permission enforcement may appear to be bypassed during testing.\n")
    lines.append("- Next step is typically either: (1) add missing permission codes to the catalog, and/or (2) extend `_infer_permission_code` to recognize additional action endpoints (eg. `journal.post`).\n")

    REPORT_MD.write_text("".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
