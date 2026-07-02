"""Abstract base class for leaderboard ranking metrics."""
from __future__ import annotations
from abc import ABC, abstractmethod


def to_float(value, default: float = 0.0) -> float:
    if value in (None, '', False):
        return default
    try:
        return float(value)
    except Exception:
        return default


class RaceMetric(ABC):
    """
    One leaderboard metric (weight / count / points / …).

    Contract
    --------
    • invoice_types  — which Invoice.invoice_type values to aggregate
    • require_employee_id — filter out invoices that have no employee_id
    • key            — API response value for 'metric' field ('weight_g', 'count', 'points')
    • score_precision — decimal places used when rounding score in the response
    • collect()      — run DB queries and return (ranking_raw, aux).
                       ranking_raw is a list of dicts; each dict must contain:
                         id, name, photo, count, weight, points,
                         sales_amount, purchase_amount, points_sales, points_purchase
                       aux is metric-specific carry-forward data (e.g. loaded invoices).
    • extract_score() — pick the ranking score from a ranking_raw row.
    • compute_team_weight() — team aggregate for weekly/monthly goal display.
                              Returns (team_weight_g, team_points_or_none).
                              team_points_or_none=None → caller derives it from weight * ppg.
    """

    @property
    @abstractmethod
    def invoice_types(self) -> list[str]: ...

    @property
    def require_employee_id(self) -> bool:
        return True

    @property
    @abstractmethod
    def key(self) -> str: ...

    @property
    def score_precision(self) -> int:
        return 0

    @abstractmethod
    def collect(
        self, base_filters: list, points_per_gram: float
    ) -> tuple[list[dict], object]: ...

    @abstractmethod
    def extract_score(self, row: dict) -> float: ...

    def compute_team_weight(
        self,
        base_filters: list,
        points_per_gram: float,
        aux: object = None,
    ) -> tuple[float, int | None]:
        return 0.0, None
