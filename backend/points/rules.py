from __future__ import annotations
from .models import PointRule
from .defaults import DEFAULT_MULTIPLIER


class RuleEngine:
    @staticmethod
    def resolve(
        rules: list[PointRule],
        *,
        category_id: int | None,
        karat: float | None,
        default: float = DEFAULT_MULTIPLIER,
    ) -> float:
        """Return the multiplier for (category_id, karat) using priority:
        (cat+karat) > (cat only) > (karat only) > default.
        Rule list order has no effect on the outcome.
        """
        best: PointRule | None = None

        for rule in rules:
            if not _matches(rule, category_id=category_id, karat=karat):
                continue
            if best is None or rule._specificity > best._specificity:
                best = rule

        return best.multiplier if best is not None else default


def _matches(rule: PointRule, *, category_id: int | None, karat: float | None) -> bool:
    if rule.category_id is not None and rule.category_id != category_id:
        return False
    if rule.karat is not None and rule.karat != karat:
        return False
    # A rule with category_id set must not match when category_id is None in the call
    if rule.category_id is not None and category_id is None:
        return False
    # A rule with karat set must not match when karat is None in the call
    if rule.karat is not None and karat is None:
        return False
    return True
