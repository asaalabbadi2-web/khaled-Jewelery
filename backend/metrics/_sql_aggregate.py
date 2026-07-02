"""Shared SQL GROUP BY base for weight and count metrics (sales invoices only)."""
from __future__ import annotations
from sqlalchemy import func

from .base import RaceMetric, to_float


class SqlAggregateMetric(RaceMetric):
    """
    Collects data via a single SQL GROUP BY employee_id query on 'بيع' invoices.
    Subclasses only need to declare key, score_precision, and extract_score.
    """

    @property
    def invoice_types(self) -> list[str]:
        return ['بيع']

    @property
    def require_employee_id(self) -> bool:
        return True

    def collect(
        self, base_filters: list, points_per_gram: float
    ) -> tuple[list[dict], None]:
        from models import db, Invoice, Employee

        rows = (
            db.session.query(
                Invoice.employee_id.label('employee_id'),
                func.count(Invoice.id).label('count'),
                func.coalesce(func.sum(Invoice.total_weight), 0.0).label('weight_sum'),
                func.coalesce(func.sum(Invoice.total), 0.0).label('cash_sum'),
                func.coalesce(func.sum(Invoice.profit_cash), 0.0).label('profit_sum'),
            )
            .filter(*base_filters)
            .group_by(Invoice.employee_id)
            .all()
        )

        employee_ids = [
            int(r.employee_id)
            for r in rows
            if getattr(r, 'employee_id', None) is not None
        ]
        name_map: dict[int, str] = {}
        photo_map: dict[int, object] = {}
        if employee_ids:
            try:
                emps = Employee.query.filter(Employee.id.in_(employee_ids)).all()
                name_map  = {int(e.id): (e.name or '').strip() for e in emps}
                photo_map = {int(e.id): getattr(e, 'photo', None) for e in emps}
            except Exception:
                pass

        ranking_raw: list[dict] = []
        for r in rows:
            emp_id = int(r.employee_id)
            ranking_raw.append({
                'id':              emp_id,
                'name':            name_map.get(emp_id) or f'Employee {emp_id}',
                'photo':           photo_map.get(emp_id),
                'count':           int(getattr(r, 'count', 0) or 0),
                'weight':          round(to_float(getattr(r, 'weight_sum', 0.0), 0.0), 3),
                'points':          0,
                'sales_amount':    round(to_float(getattr(r, 'cash_sum', 0.0), 0.0), 2),
                'purchase_amount': 0.0,
                'points_sales':    0,
                'points_purchase': 0,
            })
        return ranking_raw, None

    def compute_team_weight(
        self,
        base_filters: list,
        points_per_gram: float,
        aux: object = None,
    ) -> tuple[float, None]:
        from models import db, Invoice

        val = (
            db.session.query(func.coalesce(func.sum(Invoice.total_weight), 0.0))
            .filter(*base_filters)
            .scalar()
        )
        return round(to_float(val, 0.0), 3), None
