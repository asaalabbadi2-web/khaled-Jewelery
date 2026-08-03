"""
points/engine.py — canonical points formula.

Single implementation shared by Race (PointsMetric) and Bonus (BonusCalculator).
Any change here propagates to both systems simultaneously — never duplicate this logic.

Public API:
    compute_invoices_points(invoices, *, points_source, cash_amount_per_point,
                            points_per_gram, point_rules=None, main_karat=None) -> float
"""
from __future__ import annotations


def compute_invoices_points(
    invoices: list,
    *,
    points_source: str,
    cash_amount_per_point: float,
    points_per_gram: float,
    point_rules: list | None = None,
    main_karat: float | None = None,
    points_per_invoice: float = 1.0,
) -> float:
    """Return total points for a pre-filtered list of invoices (single actor).

    Mirrors PointsMetric._group_and_score per-invoice logic exactly.

    Args:
        invoices:              Invoice ORM objects for one actor/employee.
        points_source:         'profit_cash' | 'gold_weight' | 'sales_amount' |
                               'invoice_count' | 'sold_weight'
        cash_amount_per_point: SAR per point (for profit_cash / sales_amount modes).
        points_per_gram:       pts per main-karat-equivalent gram.
        point_rules:           PointRule list for per-category multipliers (gold_weight mode).
        main_karat:            System main karat (read from Settings when None).
    """
    from points.calculator import PointCalculator

    _ppg     = max(0.0, float(points_per_gram))
    _cpp     = max(0.01, float(cash_amount_per_point))
    _rules   = list(point_rules or [])

    def _is_purchase(inv) -> bool:
        return str(getattr(inv, 'invoice_type', '') or '').strip() == 'شراء من عميل'

    # ── profit_cash mode ──────────────────────────────────────────────────────
    if points_source == 'profit_cash':
        total = 0.0
        for inv in invoices:
            if _is_purchase(inv):
                pg = max(0.0, float(getattr(inv, 'profit_gold', 0.0) or 0.0))
                total += pg * _ppg
            else:
                pc = max(0.0, float(getattr(inv, 'profit_cash', 0.0) or 0.0))
                total += pc / _cpp
        return total

    # ── sales_amount mode ─────────────────────────────────────────────────────
    if points_source == 'sales_amount':
        total = sum(
            max(0.0, float(getattr(inv, 'total', 0.0) or 0.0))
            for inv in invoices
        )
        return total / _cpp

    # ── invoice_count mode ────────────────────────────────────────────────────
    if points_source == 'invoice_count':
        return float(len(invoices)) * max(0.0, float(points_per_invoice))

    # ── sold_weight mode ──────────────────────────────────────────────────────
    if points_source == 'sold_weight':
        total_w = sum(
            max(0.0, float(item.weight or 0.0))
            for inv in invoices
            for item in (getattr(inv, 'items', None) or [])
        )
        return total_w * _ppg

    # ── gold_weight mode (default) ────────────────────────────────────────────
    # Phase 1: accumulate per-(category, karat) buckets from InvoiceItem.profit_weight.
    # Phase 2: apply PointCalculator multiplier per bucket.
    # Backward-compat: invoices with no profit_weight on any item fall back to
    # invoice.profit_gold (permanent, matches pre-Phase-2C records).
    try:
        from models import _configured_main_karat_f
        _mk = float(main_karat or _configured_main_karat_f())
    except Exception:
        _mk = float(main_karat or 21.0)

    buckets: dict[tuple, float] = {}

    for inv in invoices:
        inv_contributed = 0.0
        for item in (getattr(inv, 'items', None) or []):
            karat = getattr(item, 'karat', None)
            if not karat:
                continue
            pw = max(0.0, float(getattr(item, 'profit_weight', 0.0) or 0.0))
            if pw == 0.0:
                continue
            normalized = pw * float(karat) / _mk
            inv_contributed += normalized
            bucket = (getattr(item, 'category_id', None), float(karat))
            buckets[bucket] = buckets.get(bucket, 0.0) + normalized

        if inv_contributed == 0.0:
            pg = max(0.0, float(getattr(inv, 'profit_gold', 0.0) or 0.0))
            if pg > 0.0:
                fb = (None, None)
                buckets[fb] = buckets.get(fb, 0.0) + pg

    total = 0.0
    for (cat_id, karat), profit in buckets.items():
        multiplier = PointCalculator.calculate(
            category_id=cat_id,
            karat=karat,
            rules=_rules,
            default=_ppg,
        )
        total += profit * multiplier

    return total
