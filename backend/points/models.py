from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PointRule:
    multiplier: float
    category_id: int | None = None
    karat: float | None = None

    @property
    def _specificity(self) -> int:
        """Higher = more specific. Used by RuleEngine to rank candidates."""
        return (self.category_id is not None) * 2 + (self.karat is not None)
