#!/usr/bin/env python3
"""Reconcile Sales Overview report totals vs SalesDB.xlsx import source.

This is a diagnostic devtool (read-only) that helps explain mismatches between:
- Excel-derived sales invoices (as parsed by import_sales_invoices.py)
- DB invoices included by the Sales Overview report endpoint logic

It prints:
- Excel invoice count/value/weight within a date range
- DB sales/returns counts and values within the same range
- The list of "extra" documents (present in DB report set but not in Excel import set)

Usage:
  DATABASE_URL=sqlite:////ABS/PATH/app.db \
    python backend/devtools/reconcile_sales_overview_vs_excel.py \
      --excel SalesDB.xlsx --start-date 2025-12-01 --end-date 2026-03-01

Notes:
- The app report counts BOTH invoice types: 'بيع' and 'مرتجع بيع'.
- By default, this script matches the report behavior of excluding unposted.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date as date_type
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

# Ensure `backend/` is importable when running from repo root.
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


@dataclass(frozen=True)
class _ExcelInvoiceSummary:
    group_key: str
    date: datetime
    employee_code: str
    employee_name: str
    total: float
    total_weight: float


def _parse_iso_ymd(value: str) -> date_type:
    s = (value or "").strip()
    if not s:
        raise ValueError("Missing date")
    return datetime.strptime(s, "%Y-%m-%d").date()


def _iso_day_start(d: date_type) -> datetime:
    return datetime(d.year, d.month, d.day)


def _format_money(v: float) -> str:
    return f"{v:,.2f}"


def _format_weight(v: float) -> str:
    return f"{v:,.3f}"


def _safe_float(v: Any) -> float:
    try:
        return float(v or 0.0)
    except Exception:
        return 0.0


def _sum_invoice_weight_from_lines(lines: Iterable[Any]) -> float:
    # ParsedRow.total_weight represents total grams for that row (all quantities).
    total = 0.0
    for ln in lines:
        try:
            total += max(0.0, float(getattr(ln, "total_weight", 0.0) or 0.0))
        except Exception:
            continue
    return float(total)


def _build_excel_summaries(
    excel_path: str,
    sheet: Optional[str],
) -> Tuple[List[_ExcelInvoiceSummary], Dict[str, int]]:
    # Reuse importer parsing logic for consistency.
    from devtools.import_sales_invoices import (  # type: ignore
        _group_invoices,
        _normalize_header,
        _parse_int,
        _parse_row,
        _read_rows,
        _read_xlsx_rows,
    )

    if str(excel_path).lower().endswith(".xlsx"):
        raw_rows = _read_xlsx_rows(excel_path, sheet_name=sheet)
    else:
        raw_rows = _read_rows(excel_path, delimiter=None)

    if not raw_rows:
        return [], {}

    fieldnames = [_normalize_header(h) for h in (raw_rows[0].keys() if raw_rows else [])]

    parsed_rows: List[Any] = []
    last_date: Optional[datetime] = None
    parse_errors = 0

    for rr in raw_rows:
        try:
            pr = _parse_row(rr, fieldnames)
            if pr is not None:
                parsed_rows.append(pr)
                last_date = pr.date
        except Exception as exc:
            # Carry-forward date like the importer.
            if "Missing date" in str(exc) and last_date is not None:
                try:
                    rr2 = dict(rr)
                    rr2["التاريخ"] = last_date.strftime("%Y/%m/%d")
                    pr = _parse_row(rr2, fieldnames)
                    if pr is not None:
                        parsed_rows.append(pr)
                        continue
                except Exception:
                    pass
            parse_errors += 1

    grouped = _group_invoices(parsed_rows)
    group_keys = sorted(grouped.keys(), key=lambda x: (_parse_int(x, 0), str(x)))

    summaries: List[_ExcelInvoiceSummary] = []
    for gk in group_keys:
        lines = grouped[gk]
        if not lines:
            continue

        first = lines[0]
        invoice_date = getattr(first, "date", None)
        if not isinstance(invoice_date, datetime):
            continue

        total_value = 0.0
        try:
            # Heuristic: if invoice-level totals are repeated, use the first non-zero.
            # Otherwise sum line_total.
            line_totals = [round(float(getattr(ln, "line_total", 0.0) or 0.0), 2) for ln in lines]
            non_zero = [v for v in line_totals if v > 0]
            if len(non_zero) > 1 and len(set(non_zero)) == 1:
                total_value = float(non_zero[0])
            else:
                total_value = float(round(sum(v for v in non_zero), 2))
        except Exception:
            total_value = 0.0

        total_weight = float(round(_sum_invoice_weight_from_lines(lines), 6))

        summaries.append(
            _ExcelInvoiceSummary(
                group_key=str(gk),
                date=invoice_date,
                employee_code=str(getattr(first, "employee_code", "") or ""),
                employee_name=str(getattr(first, "employee_name", "") or ""),
                total=float(total_value),
                total_weight=float(total_weight),
            )
        )

    meta = {
        "parsed_rows": len(parsed_rows),
        "groups": len(group_keys),
        "parse_errors": parse_errors,
    }
    return summaries, meta


def _resolve_imported_invoice_ids(
    excel_path: str,
    sheet: Optional[str],
    start_dt: Optional[datetime],
    end_dt_exclusive: Optional[datetime],
    default_customer_name: str,
) -> Tuple[Set[int], Dict[str, List[int]]]:
    """Return invoice IDs in DB that correspond to Excel groups.

    Uses the importer's dedupe signature to match each Excel group to an Invoice.
    """

    from devtools.import_sales_invoices import (  # type: ignore
        _build_invoice_payload,
        _check_auth_required,
        _ensure_default_customer,
        _find_existing_invoice_ids,
        _group_invoices,
        _infer_payment_method_ids,
        _load_employee_map,
        _normalize_header,
        _parse_int,
        _parse_row,
        _read_rows,
        _read_xlsx_rows,
    )

    if _check_auth_required():
        raise RuntimeError(
            "Settings.require_auth_for_invoice_create is enabled. "
            "Disable it temporarily to allow employee_id payload matching."
        )

    if str(excel_path).lower().endswith(".xlsx"):
        raw_rows = _read_xlsx_rows(excel_path, sheet_name=sheet)
    else:
        raw_rows = _read_rows(excel_path, delimiter=None)

    if not raw_rows:
        return set(), {}

    fieldnames = [_normalize_header(h) for h in (raw_rows[0].keys() if raw_rows else [])]

    parsed: List[Any] = []
    last_date: Optional[datetime] = None

    for rr in raw_rows:
        try:
            pr = _parse_row(rr, fieldnames)
            if pr:
                parsed.append(pr)
                last_date = pr.date
        except Exception as exc:
            if "Missing date" in str(exc) and last_date is not None:
                try:
                    rr2 = dict(rr)
                    rr2["التاريخ"] = last_date.strftime("%Y/%m/%d")
                    pr = _parse_row(rr2, fieldnames)
                    if pr:
                        parsed.append(pr)
                        continue
                except Exception:
                    pass

    grouped = _group_invoices(parsed)
    group_keys = sorted(grouped.keys(), key=lambda x: (_parse_int(x, 0), str(x)))

    employee_map = _load_employee_map()
    pm_ids = _infer_payment_method_ids()
    default_customer_id = _ensure_default_customer(None, default_customer_name)

    imported_ids: Set[int] = set()
    per_group_matches: Dict[str, List[int]] = {}

    for gk in group_keys:
        lines = grouped[gk]
        if not lines:
            continue

        # Date-range pre-filter (same as report).
        inv_dt = getattr(lines[0], "date", None)
        if isinstance(inv_dt, datetime):
            if start_dt and inv_dt < start_dt:
                continue
            if end_dt_exclusive and inv_dt >= end_dt_exclusive:
                continue

        payload, _warns = _build_invoice_payload(
            gk,
            lines,
            employee_map=employee_map,
            pm_ids=pm_ids,
            assume_cash_remainder=True,
        )

        if payload.get("invoice_type") == "بيع" and default_customer_id:
            payload["customer_id"] = int(default_customer_id)

        matches = _find_existing_invoice_ids(payload)
        per_group_matches[str(gk)] = matches
        for inv_id in matches:
            imported_ids.add(int(inv_id))

    return imported_ids, per_group_matches


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile sales overview report vs Excel")
    parser.add_argument("--excel", required=True, help="Path to SalesDB.xlsx (or exported CSV/TSV)")
    parser.add_argument("--sheet", default=None, help="Excel sheet name (if .xlsx)")
    parser.add_argument("--start-date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="YYYY-MM-DD (inclusive, like UI)")
    parser.add_argument("--include-unposted", action="store_true", help="Include unposted invoices (matches UI toggle)")
    parser.add_argument("--gold-type", default=None, help="Optional gold_type filter (new/scrap/unspecified)")
    parser.add_argument("--default-customer-name", default="عميل نقدي", help="Default customer name used during import")
    parser.add_argument("--limit-extras", type=int, default=50, help="Max extra documents to print")

    args = parser.parse_args()

    from app import app  # type: ignore

    with app.app_context():
        from models import Invoice  # type: ignore

        start_dt = None
        end_dt_excl = None
        if args.start_date:
            start_dt = _iso_day_start(_parse_iso_ymd(args.start_date))
        if args.end_date:
            end_dt_excl = _iso_day_start(_parse_iso_ymd(args.end_date)) + timedelta(days=1)

        # 1) Excel-derived summaries (same parsing rules as importer).
        excel_summaries, meta = _build_excel_summaries(args.excel, args.sheet)
        excel_summaries_in_range = [
            s
            for s in excel_summaries
            if (start_dt is None or s.date >= start_dt) and (end_dt_excl is None or s.date < end_dt_excl)
        ]

        excel_count = len(excel_summaries_in_range)
        excel_total = round(sum(s.total for s in excel_summaries_in_range), 2)
        excel_weight = round(sum(s.total_weight for s in excel_summaries_in_range), 3)

        # 2) Imported invoice IDs (as matched by dedupe signature).
        imported_ids, matches_by_group = _resolve_imported_invoice_ids(
            args.excel,
            args.sheet,
            start_dt=start_dt,
            end_dt_exclusive=end_dt_excl,
            default_customer_name=args.default_customer_name,
        )

        multi = {g: ids for g, ids in matches_by_group.items() if len(ids) > 1}
        missing = [g for g, ids in matches_by_group.items() if len(ids) == 0]

        # Detect collisions where multiple Excel groups map to the same invoice_id.
        id_to_groups: Dict[int, List[str]] = defaultdict(list)
        for gk, ids in matches_by_group.items():
            for inv_id in ids:
                try:
                    id_to_groups[int(inv_id)].append(str(gk))
                except Exception:
                    continue
        collisions = {inv_id: gks for inv_id, gks in id_to_groups.items() if len(gks) > 1}

        # 3) DB invoices included by the report (بيع + مرتجع بيع).
        sale_types = {"بيع": 1, "مرتجع بيع": -1}
        q = Invoice.query.filter(Invoice.invoice_type.in_(sale_types.keys()))
        if not args.include_unposted:
            q = q.filter(Invoice.is_posted.is_(True))
        if args.gold_type:
            q = q.filter(Invoice.gold_type == args.gold_type)
        if start_dt:
            q = q.filter(Invoice.date >= start_dt)
        if end_dt_excl:
            q = q.filter(Invoice.date < end_dt_excl)

        invoices = q.order_by(Invoice.date.asc()).all()

        db_docs = len(invoices)
        db_sales_docs = sum(1 for inv in invoices if (inv.invoice_type or "").strip() == "بيع")
        db_returns_docs = sum(1 for inv in invoices if (inv.invoice_type or "").strip() == "مرتجع بيع")

        db_gross_sales_value = round(sum(_safe_float(inv.total) for inv in invoices if (inv.invoice_type or "").strip() == "بيع"), 2)
        db_returns_value = round(sum(_safe_float(inv.total) for inv in invoices if (inv.invoice_type or "").strip() == "مرتجع بيع"), 2)
        db_net_value = round(sum(_safe_float(inv.total) * sale_types.get((inv.invoice_type or "").strip(), 1) for inv in invoices), 2)

        db_gross_sales_weight = round(sum(_safe_float(inv.total_weight) for inv in invoices if (inv.invoice_type or "").strip() == "بيع"), 3)
        db_returns_weight = round(sum(_safe_float(inv.total_weight) for inv in invoices if (inv.invoice_type or "").strip() == "مرتجع بيع"), 3)
        db_net_weight = round(sum(_safe_float(inv.total_weight) * sale_types.get((inv.invoice_type or "").strip(), 1) for inv in invoices), 3)

        # 4) Compare Excel vs DB sales-only (not returns).
        imported_sales_in_range = [inv for inv in invoices if int(inv.id) in imported_ids]
        imported_sales_value = round(sum(_safe_float(inv.total) for inv in imported_sales_in_range if (inv.invoice_type or "").strip() == "بيع"), 2)
        imported_sales_weight = round(sum(_safe_float(inv.total_weight) for inv in imported_sales_in_range if (inv.invoice_type or "").strip() == "بيع"), 3)

        extras = [inv for inv in invoices if int(inv.id) not in imported_ids]

        # Output
        print("=== Excel parse ===")
        print(f"rows_parsed={meta.get('parsed_rows')} groups={meta.get('groups')} parse_errors={meta.get('parse_errors')}")
        if args.start_date or args.end_date:
            print(f"range={args.start_date or '...'} -> {args.end_date or '...'} (inclusive)")
        print(f"excel_invoices={excel_count} excel_total={_format_money(excel_total)} excel_weight={_format_weight(excel_weight)}")

        print("\n=== DB (Sales Overview set) ===")
        print(f"include_unposted={bool(args.include_unposted)} gold_type={args.gold_type or 'ALL'}")
        print(f"db_documents={db_docs} (sales={db_sales_docs}, returns={db_returns_docs})")
        print(f"db_gross_sales_value={_format_money(db_gross_sales_value)} returns_value={_format_money(db_returns_value)} net_value={_format_money(db_net_value)}")
        print(f"db_gross_sales_weight={_format_weight(db_gross_sales_weight)} returns_weight={_format_weight(db_returns_weight)} net_weight={_format_weight(db_net_weight)}")

        print("\n=== Excel-import matched invoices (subset of DB set) ===")
        print(f"matched_invoice_ids_unique={len(imported_ids)} (in range)")
        print(f"matched_sales_value={_format_money(imported_sales_value)} matched_sales_weight={_format_weight(imported_sales_weight)}")

        delta_value = round(excel_total - imported_sales_value, 2)
        delta_weight = round(excel_weight - imported_sales_weight, 3)
        print(f"excel_minus_matched_value={_format_money(delta_value)} excel_minus_matched_weight={_format_weight(delta_weight)}")

        if missing:
            print(f"WARNING missing_matches={len(missing)} (first 10): {missing[:10]}")
        if multi:
            first_key = next(iter(multi.keys()))
            print(f"WARNING multi_matches={len(multi)} example={first_key}:{multi[first_key]}")

        if collisions:
            print(f"WARNING dedupe_collisions={len(collisions)} (multiple Excel groups map to same invoice_id)")
            shown = 0
            for inv_id, gks in sorted(collisions.items(), key=lambda kv: kv[0]):
                if shown >= 10:
                    break
                print(f"  - invoice_id={inv_id} groups={gks[:12]}{' ...' if len(gks) > 12 else ''}")
                shown += 1

        print("\n=== Extra documents (in report set but not from Excel import) ===")
        print(f"extras_count={len(extras)}")
        for inv in extras[: max(0, int(args.limit_extras))]:
            print(
                " - "
                f"id={int(inv.id)} date={getattr(inv, 'date', None).date() if getattr(inv, 'date', None) else None} "
                f"type={getattr(inv, 'invoice_type', None)} posted={bool(getattr(inv, 'is_posted', False))} "
                f"total={_format_money(_safe_float(getattr(inv, 'total', 0.0)))} "
                f"weight={_format_weight(_safe_float(getattr(inv, 'total_weight', 0.0)))} "
                f"cust={getattr(inv, 'customer_id', None)} emp={getattr(inv, 'employee_id', None)}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
