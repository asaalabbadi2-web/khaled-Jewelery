from __future__ import annotations
from ._sql_aggregate import SqlAggregateMetric


class CountMetric(SqlAggregateMetric):
    """Ranks employees by number of sales invoices."""

    @property
    def key(self) -> str:
        return 'count'

    @property
    def score_precision(self) -> int:
        return 0

    def extract_score(self, row: dict) -> float:
        return float(int(row.get('count', 0) or 0))
