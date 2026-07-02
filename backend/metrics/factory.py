from __future__ import annotations
from .base import RaceMetric
from .weight_metric import WeightMetric
from .count_metric import CountMetric
from .points_metric import PointsMetric


class MetricFactory:
    _registry: dict[str, type[RaceMetric]] = {
        'weight': WeightMetric,
        'count':  CountMetric,
        'points': PointsMetric,
    }

    @classmethod
    def create(
        cls,
        metric_name: str,
        points_per_gram: float = 10.0,
        rules: list | None = None,
    ) -> RaceMetric:
        metric_cls = cls._registry.get(metric_name)
        if metric_cls is None:
            raise ValueError(
                f'Unknown metric: {metric_name!r}. '
                f'Valid values: {list(cls._registry)}'
            )
        if metric_name == 'points':
            return metric_cls(rules=rules)
        return metric_cls()

    @classmethod
    def valid_names(cls) -> list[str]:
        return list(cls._registry)
