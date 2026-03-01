#!/usr/bin/env python3
"""Verify SalesDB.xlsx invoice group import completeness.

Checks that for each invoice group in the Excel file, exactly one matching invoice
exists in the database according to the same signature/dedupe logic used by the
sales importer.

Exit codes:
- 0: all groups have exactly one match
- 2: at least one group missing or has multiple matches
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Tuple


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Verify Sales invoice import completeness")
    p.add_argument("--input", required=True, help="Path to SalesDB.xlsx")
    p.add_argument("--min-group", type=int, default=None)
    p.add_argument("--max-group", type=int, default=None)
    p.add_argument(
        "--show-missing",
        type=int,
        default=30,
        help="How many missing groups to print (default: 30)",
    )
    p.add_argument(
        "--show-multi",
        type=int,
        default=10,
        help="How many multi-match groups to print (default: 10)",
    )
    return p.parse_args()


def _to_int_group_key(group_key: str) -> int | None:
    try:
        return int(float(str(group_key).strip()))
    except Exception:
        return None


def main() -> int:
    args = _parse_args()

    # Ensure we can import backend modules regardless of cwd
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    backend_root = os.path.join(repo_root, "backend")
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)

    from app import app  # noqa: WPS433
    from devtools.import_sales_invoices import (  # noqa: WPS433
        _build_invoice_payload,
        _ensure_default_customer,
        _find_existing_invoice_ids,
        _group_invoices,
        _infer_payment_method_ids,
        _load_employee_map,
        _normalize_header,
        _parse_row,
        _read_xlsx_rows,
    )

    with app.app_context():
        raw_rows = _read_xlsx_rows(args.input)
        fieldnames = [_normalize_header(h) for h in raw_rows[0].keys()]

        parsed = []
        last_date = None
        for rr in raw_rows:
            try:
                pr = _parse_row(rr, fieldnames)
                if pr:
                    parsed.append(pr)
                    last_date = pr.date
            except Exception as exc:
                if "Missing date" in str(exc) and last_date is not None:
                    rr = dict(rr)
                    rr["التاريخ"] = last_date.strftime("%Y/%m/%d")
                    pr = _parse_row(rr, fieldnames)
                    if pr:
                        parsed.append(pr)
                else:
                    continue

        grouped = _group_invoices(parsed)
        employee_map = _load_employee_map()
        pm_ids = _infer_payment_method_ids()
        default_customer_id = _ensure_default_customer(None, "عميل نقدي")

        missing: List[str] = []
        multi: List[Tuple[str, List[int]]] = []
        collisions: Dict[int, List[str]] = {}
        ok = 0
        checked = 0

        def in_range(gk: str) -> bool:
            igk = _to_int_group_key(gk)
            if igk is None:
                return False
            if args.min_group is not None and igk < args.min_group:
                return False
            if args.max_group is not None and igk > args.max_group:
                return False
            return True

        group_keys = [gk for gk in grouped.keys() if in_range(gk)]
        group_keys.sort(key=lambda k: _to_int_group_key(k) or 10**18)

        matches_by_group: Dict[str, List[int]] = {}

        for gk in group_keys:
            checked += 1
            payload, _warns = _build_invoice_payload(
                gk,
                grouped[gk],
                employee_map,
                pm_ids,
                assume_cash_remainder=True,
            )
            if default_customer_id:
                payload["customer_id"] = int(default_customer_id)

            existing_ids = _find_existing_invoice_ids(payload)
            matches_by_group[str(gk)] = list(existing_ids)
            if not existing_ids:
                missing.append(gk)
            elif len(existing_ids) > 1:
                multi.append((gk, existing_ids))
            else:
                ok += 1

        # Detect collisions where multiple groups map to the same invoice_id.
        id_to_groups: Dict[int, List[str]] = {}
        for gk, ids in matches_by_group.items():
            for inv_id in ids:
                try:
                    inv_int = int(inv_id)
                except Exception:
                    continue
                id_to_groups.setdefault(inv_int, []).append(gk)

        collisions = {inv_id: gks for inv_id, gks in id_to_groups.items() if len(gks) > 1}

        print("groups_total", len(grouped))
        print("groups_checked", checked)
        print("ok_exactly_one", ok)
        print("missing_count", len(missing))
        print("multi_count", len(multi))
        print("collision_count", len(collisions))

        if missing:
            print("missing_sample", missing[: args.show_missing])
        if multi:
            sample = [(gk, ids[:5], len(ids)) for gk, ids in multi[: args.show_multi]]
            print("multi_sample", sample)

        if collisions:
            # Show up to 10 collisions with up to 12 group keys each.
            sample = []
            for inv_id, gks in sorted(collisions.items(), key=lambda kv: kv[0])[:10]:
                sample.append((inv_id, gks[:12], len(gks)))
            print("collision_sample", sample)

        return 0 if (not missing and not multi and not collisions) else 2


if __name__ == "__main__":
    raise SystemExit(main())
