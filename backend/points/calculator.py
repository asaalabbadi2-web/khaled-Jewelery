from __future__ import annotations
from .models import PointRule
from .rules import RuleEngine
from .defaults import DEFAULT_MULTIPLIER


class PointCalculator:
    @staticmethod
    def calculate(
        *,
        category_id: int | None = None,
        karat: float | None = None,
        rules: list[PointRule] | None = None,
        default: float = DEFAULT_MULTIPLIER,
    ) -> float:
        """Return the points multiplier for a given (category_id, karat) pair.

        Caller supplies the active rule set and the default multiplier
        (typically points_per_gram from settings).
        """
        if not rules:
            return default
        return RuleEngine.resolve(
            rules, category_id=category_id, karat=karat, default=default
        )
