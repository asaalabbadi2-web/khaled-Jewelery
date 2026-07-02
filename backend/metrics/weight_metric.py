from __future__ import annotations
from ._sql_aggregate import SqlAggregateMetric


class WeightMetric(SqlAggregateMetric):
    """Ranks employees by total weight sold (grams)."""

    @property
    def key(self) -> str:
        return 'weight_g'

    @property
    def score_precision(self) -> int:
        return 3

    def extract_score(self, row: dict) -> float:
        return float(row.get('weight', 0.0))
