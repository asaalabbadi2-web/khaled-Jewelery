"""Points-based leaderboard metric — per-item (category, karat) rule engine."""
from __future__ import annotations
from .base import RaceMetric


class PointsMetric(RaceMetric):
    """
    Ranks employees by points derived from InvoiceItem-level profit.

    Calculation:
        bucket_profit = Σ(item.profit_weight × item.karat / main_karat)
        points        = Σ_buckets(bucket_profit × multiplier(category_id, karat))

    Where multiplier comes from PointCalculator (falls back to points_per_gram
    when no rule matches).  With default rules this equals the legacy formula:
        profit_gold × points_per_gram
    because profit_gold = Σ(profit_weight × karat / main_karat) by construction.

    Covers both 'بيع' and 'شراء من عميل' invoice types.
    Attributes invoices to employees via employee_id with posted_by fallback.
    """

    def __init__(self, rules: list | None = None) -> None:
        self._rules = list(rules) if rules else []

    @property
    def invoice_types(self) -> list[str]:
        return ['بيع', 'شراء من عميل']

    @property
    def require_employee_id(self) -> bool:
        return False

    @property
    def key(self) -> str:
        return 'points'

    @property
    def score_precision(self) -> int:
        return 0

    # ── Phase 1: collect rows ─────────────────────────────────────────────────

    @staticmethod
    def _load_invoices(base_filters: list) -> list:
        from models import Invoice
        from sqlalchemy.orm import subqueryload
        return (
            Invoice.query
            .options(subqueryload(Invoice.items))
            .filter(*base_filters)
            .all()
        )

    # ── Phase 2: infer actor ──────────────────────────────────────────────────

    @staticmethod
    def _normalize_key(value: str) -> str:
        return (value or '').strip().lower()

    @staticmethod
    def _infer_employee_id(inv) -> int | None:
        from models import AppUser, Employee
        from sqlalchemy import func as sa_func

        try:
            if getattr(inv, 'employee_id', None) not in (None, '', 0, '0', False):
                return int(inv.employee_id)
        except Exception:
            pass

        posted_by = PointsMetric._normalize_key(
            str(getattr(inv, 'posted_by', '') or '')
        )
        if not posted_by:
            return None

        try:
            app_user = AppUser.query.filter(
                sa_func.lower(sa_func.trim(AppUser.username)) == posted_by
            ).first()
            if app_user and getattr(app_user, 'employee_id', None):
                return int(app_user.employee_id)
        except Exception:
            pass

        try:
            app_user = AppUser.query.filter(
                sa_func.lower(sa_func.trim(
                    sa_func.coalesce(AppUser.full_name, '')
                )) == posted_by
            ).first()
            if app_user and getattr(app_user, 'employee_id', None):
                return int(app_user.employee_id)
        except Exception:
            pass

        try:
            emp = Employee.query.filter(
                sa_func.lower(sa_func.trim(
                    sa_func.coalesce(Employee.name, '')
                )) == posted_by
            ).first()
            if emp:
                return int(emp.id)
        except Exception:
            pass

        return None

    @staticmethod
    def _infer_actor(inv) -> tuple[int, str] | None:
        from models import Employee

        emp_id = PointsMetric._infer_employee_id(inv)
        if emp_id:
            try:
                emp = Employee.query.get(emp_id)
                if emp and (emp.name or '').strip():
                    return int(emp_id), (emp.name or '').strip()
            except Exception:
                pass
            return int(emp_id), f'Employee {int(emp_id)}'

        posted_by_raw = str(getattr(inv, 'posted_by', '') or '').strip()
        if not posted_by_raw:
            return None

        try:
            import zlib
            actor_id = -int(zlib.adler32(posted_by_raw.encode('utf-8')) or 1)
        except Exception:
            actor_id = -1
        return actor_id, posted_by_raw

    # ── Phase 3: group and score ──────────────────────────────────────────────

    def _group_and_score(
        self, invoices: list, points_per_gram: float
    ) -> tuple[dict, dict, dict, dict, dict, dict, dict]:
        """Bucket items by (actor_id, category_id, karat), apply PointCalculator,
        and return per-actor aggregates.

        Returns:
            counts, actor_name_map, sales_amount, purchase_amount,
            pts_total, pts_sales, pts_purchase
        """
        from models import _configured_main_karat_f
        from points.calculator import PointCalculator

        main_karat = _configured_main_karat_f()

        counts:          dict[int, int]   = {}
        actor_name_map:  dict[int, str]   = {}
        sales_amount:    dict[int, float] = {}
        purchase_amount: dict[int, float] = {}

        # (actor_id, category_id, karat) → normalized_profit_gold_equivalent
        buckets_total:    dict[tuple, float] = {}
        buckets_sales:    dict[tuple, float] = {}
        buckets_purchase: dict[tuple, float] = {}

        for inv in invoices:
            actor = self._infer_actor(inv)
            if not actor:
                continue
            actor_id, actor_name = actor
            aid = int(actor_id)
            actor_name_map[aid] = actor_name
            counts[aid] = counts.get(aid, 0) + 1

            invoice_total = float(getattr(inv, 'total', 0.0) or 0.0)
            is_purchase = (
                str(getattr(inv, 'invoice_type', '') or '').strip() == 'شراء من عميل'
            )
            if is_purchase:
                purchase_amount[aid] = purchase_amount.get(aid, 0.0) + invoice_total
            else:
                sales_amount[aid] = sales_amount.get(aid, 0.0) + invoice_total

            inv_contributed = 0.0
            for item in (inv.items or []):
                karat = item.karat
                if not karat:
                    continue
                pw = max(0.0, float(item.profit_weight or 0.0))
                if pw == 0.0:
                    continue
                # Normalize to main-karat equivalent (same unit as profit_gold)
                normalized = pw * float(karat) / main_karat
                inv_contributed += normalized
                bucket = (aid, item.category_id, float(karat))
                buckets_total[bucket] = buckets_total.get(bucket, 0.0) + normalized
                if is_purchase:
                    buckets_purchase[bucket] = (
                        buckets_purchase.get(bucket, 0.0) + normalized
                    )
                else:
                    buckets_sales[bucket] = (
                        buckets_sales.get(bucket, 0.0) + normalized
                    )

            # Backward compatibility layer (permanent, not temporary):
            # Invoices created before Phase 2C — or imported from older systems —
            # have InvoiceItem.profit_weight == 0 because that field was never
            # populated at write time.  Fall back to invoice.profit_gold so that
            # historical leaderboards remain unchanged.  Once Phase 2C is in
            # production, new invoices will always hit the per-item path above;
            # this branch will still protect legacy and imported records.
            if inv_contributed == 0.0:
                pg = max(0.0, float(getattr(inv, 'profit_gold', 0.0) or 0.0))
                if pg > 0.0:
                    fb = (aid, None, None)
                    buckets_total[fb] = buckets_total.get(fb, 0.0) + pg
                    if is_purchase:
                        buckets_purchase[fb] = buckets_purchase.get(fb, 0.0) + pg
                    else:
                        buckets_sales[fb] = buckets_sales.get(fb, 0.0) + pg

        def _apply_rules(buckets: dict) -> dict[int, float]:
            actor_pts: dict[int, float] = {}
            for (aid, cat_id, karat), profit in buckets.items():
                multiplier = PointCalculator.calculate(
                    category_id=cat_id,
                    karat=karat,
                    rules=self._rules,
                    default=points_per_gram,
                )
                actor_pts[aid] = actor_pts.get(aid, 0.0) + profit * multiplier
            return actor_pts

        pts_total    = _apply_rules(buckets_total)
        pts_sales    = _apply_rules(buckets_sales)
        pts_purchase = _apply_rules(buckets_purchase)

        return (
            counts, actor_name_map, sales_amount, purchase_amount,
            pts_total, pts_sales, pts_purchase,
        )

    # ── main interface ────────────────────────────────────────────────────────

    def collect(
        self, base_filters: list, points_per_gram: float
    ) -> tuple[list[dict], list]:
        from models import Employee

        # Phase 1
        invoices = self._load_invoices(base_filters)

        # Phases 2 + 3
        (
            counts, actor_name_map, sales_amount, purchase_amount,
            pts_total, pts_sales, pts_purchase,
        ) = self._group_and_score(invoices, points_per_gram)

        # Phase 4: resolve names/photos, build ranking_raw
        real_ids = [aid for aid in counts if aid > 0]
        name_map:  dict[int, str]    = dict(actor_name_map)
        photo_map: dict[int, object] = {}
        if real_ids:
            try:
                emps = Employee.query.filter(Employee.id.in_(real_ids)).all()
                for e in emps:
                    eid = int(e.id)
                    name_map[eid]  = (e.name or '').strip() or name_map.get(eid, f'Employee {eid}')
                    photo_map[eid] = getattr(e, 'photo', None)
            except Exception:
                pass

        ranking_raw: list[dict] = []
        for actor_id in counts:
            aid = int(actor_id)
            ranking_raw.append({
                'id':              aid,
                'name':            name_map.get(aid) or f'Employee {aid}',
                'photo':           photo_map.get(aid),
                'count':           counts.get(aid, 0),
                'weight':          0.0,
                'points':          max(0, int(round(pts_total.get(aid, 0.0)))),
                'sales_amount':    round(sales_amount.get(aid, 0.0), 2),
                'purchase_amount': round(purchase_amount.get(aid, 0.0), 2),
                'points_sales':    max(0, int(round(pts_sales.get(aid, 0.0)))),
                'points_purchase': max(0, int(round(pts_purchase.get(aid, 0.0)))),
            })

        return ranking_raw, invoices

    def extract_score(self, row: dict) -> float:
        return float(int(row.get('points', 0) or 0))

    def compute_team_weight(
        self,
        base_filters: list,
        points_per_gram: float,
        aux: object = None,
    ) -> tuple[float, int]:
        from models import Invoice

        invoices = aux if aux is not None else Invoice.query.filter(*base_filters).all()
        team_weight_main = sum(
            max(0.0, float(getattr(inv, 'profit_gold', 0.0) or 0.0))
            for inv in invoices
        )
        team_weight_g = round(team_weight_main, 3)
        team_points   = int(round(team_weight_main * points_per_gram))
        return team_weight_g, team_points
