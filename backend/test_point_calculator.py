"""Unit tests for PointCalculator — drives the public interface design."""
import pytest
from points.models import PointRule
from points.calculator import PointCalculator
from points.defaults import DEFAULT_MULTIPLIER


class TestDefaultBehavior:
    """Without any rules, always return DEFAULT_MULTIPLIER."""

    def test_no_args_returns_default(self):
        assert PointCalculator.calculate() == DEFAULT_MULTIPLIER

    def test_category_only_no_rules_returns_default(self):
        assert PointCalculator.calculate(category_id=1) == DEFAULT_MULTIPLIER

    def test_karat_only_no_rules_returns_default(self):
        assert PointCalculator.calculate(karat=21.0) == DEFAULT_MULTIPLIER

    def test_both_dimensions_no_rules_returns_default(self):
        assert PointCalculator.calculate(category_id=1, karat=21.0) == DEFAULT_MULTIPLIER

    def test_empty_rules_list_returns_default(self):
        assert PointCalculator.calculate(category_id=1, karat=21.0, rules=[]) == DEFAULT_MULTIPLIER

    def test_default_multiplier_is_ten(self):
        assert DEFAULT_MULTIPLIER == 10.0


class TestExactMatch:
    """(category_id + karat) is the highest specificity level."""

    def test_exact_match_returns_rule_multiplier(self):
        rules = [PointRule(category_id=1, karat=21.0, multiplier=15.0)]
        assert PointCalculator.calculate(category_id=1, karat=21.0, rules=rules) == 15.0

    def test_same_category_different_karat_returns_default(self):
        rules = [PointRule(category_id=1, karat=21.0, multiplier=15.0)]
        assert PointCalculator.calculate(category_id=1, karat=18.0, rules=rules) == DEFAULT_MULTIPLIER

    def test_same_karat_different_category_returns_default(self):
        rules = [PointRule(category_id=1, karat=21.0, multiplier=15.0)]
        assert PointCalculator.calculate(category_id=2, karat=21.0, rules=rules) == DEFAULT_MULTIPLIER

    def test_two_exact_rules_each_matches_correctly(self):
        rules = [
            PointRule(category_id=1, karat=21.0, multiplier=10.0),
            PointRule(category_id=1, karat=18.0, multiplier=8.0),
        ]
        assert PointCalculator.calculate(category_id=1, karat=21.0, rules=rules) == 10.0
        assert PointCalculator.calculate(category_id=1, karat=18.0, rules=rules) == 8.0


class TestCategoryOnlyMatch:
    """A rule with karat=None applies to any karat within that category."""

    def test_category_only_rule_no_karat_arg(self):
        rules = [PointRule(category_id=3, karat=None, multiplier=5.0)]
        assert PointCalculator.calculate(category_id=3, rules=rules) == 5.0

    def test_category_only_rule_with_unmatched_karat(self):
        rules = [PointRule(category_id=3, karat=None, multiplier=5.0)]
        assert PointCalculator.calculate(category_id=3, karat=18.0, rules=rules) == 5.0

    def test_category_only_rule_wrong_category_returns_default(self):
        rules = [PointRule(category_id=3, karat=None, multiplier=5.0)]
        assert PointCalculator.calculate(category_id=99, rules=rules) == DEFAULT_MULTIPLIER


class TestKaratOnlyMatch:
    """A rule with category_id=None applies to any category with that karat."""

    def test_karat_only_rule_no_category_arg(self):
        rules = [PointRule(category_id=None, karat=18.0, multiplier=8.0)]
        assert PointCalculator.calculate(karat=18.0, rules=rules) == 8.0

    def test_karat_only_rule_with_unmatched_category(self):
        rules = [PointRule(category_id=None, karat=18.0, multiplier=8.0)]
        assert PointCalculator.calculate(category_id=7, karat=18.0, rules=rules) == 8.0

    def test_karat_only_rule_wrong_karat_returns_default(self):
        rules = [PointRule(category_id=None, karat=18.0, multiplier=8.0)]
        assert PointCalculator.calculate(karat=21.0, rules=rules) == DEFAULT_MULTIPLIER


class TestSpecificityPriority:
    """Priority must be: (cat+karat) > (cat only) > (karat only) > default."""

    RULES = [
        PointRule(category_id=1, karat=21.0, multiplier=15.0),    # cat+karat
        PointRule(category_id=1, karat=None,  multiplier=8.0),    # cat only
        PointRule(category_id=None, karat=21.0, multiplier=6.0),  # karat only
    ]

    def test_exact_beats_category_only(self):
        assert PointCalculator.calculate(category_id=1, karat=21.0, rules=self.RULES) == 15.0

    def test_category_only_beats_karat_only(self):
        # cat=1 has a category rule; karat=18 has no karat-only or exact rule for cat=1
        assert PointCalculator.calculate(category_id=1, karat=18.0, rules=self.RULES) == 8.0

    def test_karat_only_beats_default(self):
        # cat=2 has no category rule; karat=21 has a karat-only rule
        assert PointCalculator.calculate(category_id=2, karat=21.0, rules=self.RULES) == 6.0

    def test_default_when_nothing_matches(self):
        assert PointCalculator.calculate(category_id=2, karat=18.0, rules=self.RULES) == DEFAULT_MULTIPLIER


class TestRuleOrderIndependence:
    """Specificity, not list order, determines which rule wins."""

    def test_exact_wins_regardless_of_position(self):
        rules_forward = [
            PointRule(category_id=1, karat=21.0, multiplier=15.0),
            PointRule(category_id=1, karat=None, multiplier=8.0),
        ]
        rules_reversed = list(reversed(rules_forward))
        assert PointCalculator.calculate(category_id=1, karat=21.0, rules=rules_forward) == 15.0
        assert PointCalculator.calculate(category_id=1, karat=21.0, rules=rules_reversed) == 15.0

    def test_category_fallback_stable_across_orderings(self):
        rules = [
            PointRule(category_id=1, karat=21.0, multiplier=15.0),
            PointRule(category_id=1, karat=None,  multiplier=8.0),
            PointRule(category_id=None, karat=21.0, multiplier=6.0),
        ]
        orderings = [
            rules,
            list(reversed(rules)),
            [rules[2], rules[0], rules[1]],
        ]
        for r in orderings:
            assert PointCalculator.calculate(category_id=1, karat=18.0, rules=r) == 8.0
            assert PointCalculator.calculate(category_id=2, karat=21.0, rules=r) == 6.0


class TestNonMatchingRulesIgnored:
    """Unrelated rules must have zero effect on unrelated lookups."""

    def test_unrelated_rules_give_default(self):
        rules = [
            PointRule(category_id=99, karat=24.0, multiplier=2.0),
            PointRule(category_id=100, karat=None, multiplier=3.0),
        ]
        assert PointCalculator.calculate(category_id=1, karat=21.0, rules=rules) == DEFAULT_MULTIPLIER

    def test_exact_rule_does_not_act_as_category_fallback(self):
        # Rule is (cat=1, karat=18) — it has a karat component,
        # so it must NOT serve as a wildcard for other karats in cat=1.
        rules = [PointRule(category_id=1, karat=18.0, multiplier=99.0)]
        assert PointCalculator.calculate(category_id=1, karat=21.0, rules=rules) == DEFAULT_MULTIPLIER

    def test_exact_rule_does_not_act_as_karat_fallback(self):
        # Rule is (cat=1, karat=18) — must NOT match calls with just karat=18.
        rules = [PointRule(category_id=1, karat=18.0, multiplier=99.0)]
        assert PointCalculator.calculate(category_id=2, karat=18.0, rules=rules) == DEFAULT_MULTIPLIER
