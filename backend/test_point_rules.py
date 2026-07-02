"""Unit tests for RuleEngine.resolve() — the matching and priority logic."""
import pytest
from points.models import PointRule
from points.rules import RuleEngine
from points.defaults import DEFAULT_MULTIPLIER


class TestEmptyAndNone:
    def test_empty_rules_returns_default(self):
        assert RuleEngine.resolve([], category_id=None, karat=None) == DEFAULT_MULTIPLIER

    def test_empty_rules_with_dimensions_returns_default(self):
        assert RuleEngine.resolve([], category_id=1, karat=21.0) == DEFAULT_MULTIPLIER

    def test_rules_exist_but_none_match_returns_default(self):
        rules = [PointRule(category_id=5, karat=24.0, multiplier=2.0)]
        assert RuleEngine.resolve(rules, category_id=1, karat=21.0) == DEFAULT_MULTIPLIER


class TestResolutionBySpecificity:
    def test_exact_match(self):
        rules = [PointRule(category_id=1, karat=21.0, multiplier=12.0)]
        assert RuleEngine.resolve(rules, category_id=1, karat=21.0) == 12.0

    def test_category_only_match(self):
        rules = [PointRule(category_id=2, karat=None, multiplier=7.0)]
        assert RuleEngine.resolve(rules, category_id=2, karat=18.0) == 7.0

    def test_karat_only_match(self):
        rules = [PointRule(category_id=None, karat=18.0, multiplier=8.0)]
        assert RuleEngine.resolve(rules, category_id=5, karat=18.0) == 8.0

    def test_full_priority_chain(self):
        rules = [
            PointRule(category_id=1, karat=21.0, multiplier=15.0),
            PointRule(category_id=1, karat=None,  multiplier=8.0),
            PointRule(category_id=None, karat=21.0, multiplier=6.0),
        ]
        assert RuleEngine.resolve(rules, category_id=1, karat=21.0) == 15.0  # exact
        assert RuleEngine.resolve(rules, category_id=1, karat=18.0) == 8.0   # cat only
        assert RuleEngine.resolve(rules, category_id=2, karat=21.0) == 6.0   # karat only
        assert RuleEngine.resolve(rules, category_id=2, karat=18.0) == DEFAULT_MULTIPLIER  # default


class TestNoneDimensions:
    def test_none_category_matches_karat_only_rule(self):
        rules = [PointRule(category_id=None, karat=21.0, multiplier=10.0)]
        assert RuleEngine.resolve(rules, category_id=None, karat=21.0) == 10.0

    def test_none_karat_matches_category_only_rule(self):
        rules = [PointRule(category_id=3, karat=None, multiplier=5.0)]
        assert RuleEngine.resolve(rules, category_id=3, karat=None) == 5.0

    def test_both_none_no_matching_rule_returns_default(self):
        rules = [PointRule(category_id=1, karat=21.0, multiplier=15.0)]
        assert RuleEngine.resolve(rules, category_id=None, karat=None) == DEFAULT_MULTIPLIER


class TestMultipleRulesSameTier:
    """When multiple rules exist at the same specificity level, the one that
    actually matches the call wins — there should never be ambiguity."""

    def test_two_category_only_rules_correct_one_chosen(self):
        rules = [
            PointRule(category_id=1, karat=None, multiplier=5.0),
            PointRule(category_id=2, karat=None, multiplier=7.0),
        ]
        assert RuleEngine.resolve(rules, category_id=1, karat=18.0) == 5.0
        assert RuleEngine.resolve(rules, category_id=2, karat=21.0) == 7.0

    def test_two_karat_only_rules_correct_one_chosen(self):
        rules = [
            PointRule(category_id=None, karat=18.0, multiplier=8.0),
            PointRule(category_id=None, karat=21.0, multiplier=10.0),
        ]
        assert RuleEngine.resolve(rules, category_id=5, karat=18.0) == 8.0
        assert RuleEngine.resolve(rules, category_id=5, karat=21.0) == 10.0
