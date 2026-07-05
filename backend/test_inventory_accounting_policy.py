"""Tests for InventoryAccountingPolicy — Strategy Pattern.

Covers:
  DefaultInventoryPolicy:
    - surplus line → inventory debit, surplus_account credit
    - shortage line → shortage_account debit, inventory credit
    - zero variance → treated as surplus (non-negative branch)

  ThresholdInventoryPolicy:
    - small surplus (< threshold) → operating_income
    - large surplus (>= threshold) → investigation
    - small shortage (< threshold) → operating_expense
    - large shortage (>= threshold) → investigation
    - threshold=0 is rejected
    - exact threshold value is treated as material

  InventoryAccountingService:
    - accepts policy kwarg without raising
    - uses DefaultInventoryPolicy when policy=None
    - policy label appears in RULE-3: policy class never imported by non-GL services
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from services.inventory_accounting_policy import (
    AccountPair,
    DefaultInventoryPolicy,
    InventoryAccountingPolicy,
    ThresholdInventoryPolicy,
)
from services.inventory_accounting_service import InventoryAccountingService


# ── helpers ───────────────────────────────────────────────────────────────────

def _line(variance: float):
    m = MagicMock()
    m.variance_weight = variance
    m.category_id = 1
    m.karat = 21.0
    return m


def _adjustment(lines=None, branch_id=1, reason='test'):
    adj = MagicMock()
    adj.id = 99
    adj.branch_id = branch_id
    adj.reason = reason
    adj.lines = lines or []
    return adj


# ── DefaultInventoryPolicy ────────────────────────────────────────────────────

class TestDefaultInventoryPolicy:

    def setup_method(self):
        self.policy = DefaultInventoryPolicy(
            inventory_account_id=10,
            surplus_account_id=20,
            shortage_account_id=30,
        )

    def test_surplus_routes_to_surplus_account(self):
        pair = self.policy.accounts_for_line(_line(+5.0))
        assert pair.debit_account_id == 10   # inventory
        assert pair.credit_account_id == 20  # surplus income

    def test_shortage_routes_to_shortage_account(self):
        pair = self.policy.accounts_for_line(_line(-3.0))
        assert pair.debit_account_id == 30   # shortage expense
        assert pair.credit_account_id == 10  # inventory

    def test_zero_variance_treated_as_surplus(self):
        pair = self.policy.accounts_for_line(_line(0.0))
        assert pair.debit_account_id == 10
        assert pair.credit_account_id == 20

    def test_returns_account_pair_instance(self):
        pair = self.policy.accounts_for_line(_line(1.0))
        assert isinstance(pair, AccountPair)

    def test_label_contains_class_name(self):
        assert 'DefaultInventoryPolicy' in self.policy.label()

    def test_no_account_ids_returns_none(self):
        policy = DefaultInventoryPolicy()
        pair = policy.accounts_for_line(_line(-1.0))
        assert pair.debit_account_id is None
        assert pair.credit_account_id is None


# ── ThresholdInventoryPolicy ──────────────────────────────────────────────────

class TestThresholdInventoryPolicy:

    def setup_method(self):
        self.policy = ThresholdInventoryPolicy(
            threshold_grams=2.0,
            inventory_account_id=10,
            operating_expense_account_id=31,
            operating_income_account_id=21,
            investigation_account_id=50,
        )

    def test_small_surplus_routes_to_operating_income(self):
        pair = self.policy.accounts_for_line(_line(+0.5))
        assert pair.credit_account_id == 21  # operating income
        assert pair.debit_account_id == 10   # inventory
        assert 'operating_income' in pair.label

    def test_large_surplus_routes_to_investigation(self):
        pair = self.policy.accounts_for_line(_line(+5.0))
        assert pair.credit_account_id == 50  # investigation
        assert pair.debit_account_id == 10
        assert 'investigation' in pair.label

    def test_small_shortage_routes_to_operating_expense(self):
        pair = self.policy.accounts_for_line(_line(-1.9))
        assert pair.debit_account_id == 31   # operating expense
        assert pair.credit_account_id == 10  # inventory
        assert 'operating_expense' in pair.label

    def test_large_shortage_routes_to_investigation(self):
        pair = self.policy.accounts_for_line(_line(-2.5))
        assert pair.debit_account_id == 50   # investigation
        assert pair.credit_account_id == 10
        assert 'investigation' in pair.label

    def test_exact_threshold_is_material(self):
        """A variance exactly equal to threshold must be treated as material."""
        pair = self.policy.accounts_for_line(_line(-2.0))
        assert pair.debit_account_id == 50   # investigation (not operating)

    def test_threshold_zero_raises(self):
        with pytest.raises(ValueError, match='threshold_grams must be positive'):
            ThresholdInventoryPolicy(threshold_grams=0)

    def test_label_includes_threshold(self):
        assert '2.0g' in self.policy.label()

    def test_is_subclass_of_abstract_policy(self):
        assert isinstance(self.policy, InventoryAccountingPolicy)


# ── InventoryAccountingService + policy integration ───────────────────────────

class TestAccountingServiceWithPolicy:

    def test_accepts_default_policy_kwarg(self):
        adj = _adjustment([_line(-1.0)])
        policy = DefaultInventoryPolicy(inventory_account_id=10)
        # must not raise
        InventoryAccountingService.post_adjustment_to_gl(adj, policy=policy)

    def test_accepts_threshold_policy_kwarg(self):
        adj = _adjustment([_line(+3.0)])
        policy = ThresholdInventoryPolicy(threshold_grams=2.0)
        InventoryAccountingService.post_adjustment_to_gl(adj, policy=policy)

    def test_no_policy_uses_default(self, capsys):
        adj = _adjustment([_line(-0.5)])
        InventoryAccountingService.post_adjustment_to_gl(adj)
        captured = capsys.readouterr()
        assert 'DefaultInventoryPolicy' in captured.out

    def test_policy_label_in_stub_output(self, capsys):
        adj = _adjustment([_line(-5.0)])
        policy = ThresholdInventoryPolicy(threshold_grams=2.0)
        InventoryAccountingService.post_adjustment_to_gl(adj, policy=policy)
        captured = capsys.readouterr()
        assert 'ThresholdInventoryPolicy' in captured.out

    def test_accounting_policy_not_imported_by_adjustment_service(self):
        """InventoryAdjustmentService must not import policy types directly."""
        import ast
        import pathlib

        src = pathlib.Path(__file__).parent / 'services' / 'inventory_adjustment_service.py'
        tree = ast.parse(src.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ''
                assert 'accounting_policy' not in module, (
                    'InventoryAdjustmentService must not import accounting policy types. '
                    'Policy injection is the caller\'s responsibility.'
                )
