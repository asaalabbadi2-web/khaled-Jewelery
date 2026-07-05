"""InventoryAccountingPolicy — Strategy Pattern for GL account mapping.

Each Policy implementation decides:
  - Which debit/credit accounts to use for a given adjustment line
  - Whether a line is material enough to route to an investigation account

The Strategy is injected into InventoryAccountingService.post_adjustment_to_gl():

    policy = ThresholdInventoryPolicy(threshold_grams=2.0)
    InventoryAccountingService.post_adjustment_to_gl(adjustment, policy=policy)

If no policy is supplied, DefaultInventoryPolicy is used.

Concrete implementations:
    DefaultInventoryPolicy     — all variances → single account pair
    ThresholdInventoryPolicy   — small variances → operating expense;
                                  large variances → investigation account

Adding a new policy:
    Subclass InventoryAccountingPolicy and implement accounts_for_line().
    No changes needed elsewhere.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class AccountPair:
    """Debit/credit account IDs for one adjustment line."""
    debit_account_id: Optional[int]
    credit_account_id: Optional[int]
    label: str = ''          # human-readable reason for this routing decision


class InventoryAccountingPolicy(ABC):
    """Abstract base — injected into InventoryAccountingService."""

    @abstractmethod
    def accounts_for_line(self, line) -> AccountPair:
        """Return the GL account pair for a single InventoryAdjustmentLine.

        Args:
            line: InventoryAdjustmentLine instance
                  relevant attributes: variance_weight, category_id, karat

        Returns:
            AccountPair with debit_account_id and credit_account_id.
            Either may be None — the GL builder will substitute the
            default inventory account from Settings.
        """

    def label(self) -> str:
        return self.__class__.__name__


class DefaultInventoryPolicy(InventoryAccountingPolicy):
    """Route all variances to a single configured account pair.

    Surplus  (variance > 0): DR inventory  / CR adjustment_income
    Shortage (variance < 0): DR adjustment_expense / CR inventory

    Account IDs are read from Settings at call time; pass explicit IDs to
    override (useful in tests).
    """

    def __init__(
        self,
        inventory_account_id: Optional[int] = None,
        surplus_account_id: Optional[int] = None,
        shortage_account_id: Optional[int] = None,
    ):
        self._inventory  = inventory_account_id
        self._surplus    = surplus_account_id
        self._shortage   = shortage_account_id

    def accounts_for_line(self, line) -> AccountPair:
        variance = float(getattr(line, 'variance_weight', 0) or 0)
        if variance >= 0:
            return AccountPair(
                debit_account_id=self._inventory,
                credit_account_id=self._surplus,
                label='surplus→adjustment_income',
            )
        return AccountPair(
            debit_account_id=self._shortage,
            credit_account_id=self._inventory,
            label='shortage→adjustment_expense',
        )


class ThresholdInventoryPolicy(InventoryAccountingPolicy):
    """Route variances by materiality threshold.

    |variance| < threshold_grams   → operating expense / income account
                                      (immaterial — normal manufacturing loss)
    |variance| >= threshold_grams  → investigation account
                                      (material — requires investigation)

    This mirrors the dual-track treatment common in gold manufacturing:
    small daily losses go to 'فاقد تصنيع' (manufacturing waste),
    large differences go to 'حساب التحقيق' (investigation holding account).
    """

    def __init__(
        self,
        threshold_grams: float = 2.0,
        inventory_account_id: Optional[int] = None,
        operating_expense_account_id: Optional[int] = None,
        operating_income_account_id: Optional[int] = None,
        investigation_account_id: Optional[int] = None,
    ):
        if threshold_grams <= 0:
            raise ValueError('threshold_grams must be positive')
        self.threshold_grams = threshold_grams
        self._inventory    = inventory_account_id
        self._op_expense   = operating_expense_account_id
        self._op_income    = operating_income_account_id
        self._investigation = investigation_account_id

    def accounts_for_line(self, line) -> AccountPair:
        variance = float(getattr(line, 'variance_weight', 0) or 0)
        is_material = abs(variance) >= self.threshold_grams

        if is_material:
            # Route to investigation account regardless of direction
            if variance >= 0:
                return AccountPair(
                    debit_account_id=self._inventory,
                    credit_account_id=self._investigation,
                    label=f'surplus≥{self.threshold_grams}g→investigation',
                )
            return AccountPair(
                debit_account_id=self._investigation,
                credit_account_id=self._inventory,
                label=f'shortage≥{self.threshold_grams}g→investigation',
            )

        # Immaterial — route to operating expense / income
        if variance >= 0:
            return AccountPair(
                debit_account_id=self._inventory,
                credit_account_id=self._op_income,
                label=f'surplus<{self.threshold_grams}g→operating_income',
            )
        return AccountPair(
            debit_account_id=self._op_expense,
            credit_account_id=self._inventory,
            label=f'shortage<{self.threshold_grams}g→operating_expense',
        )

    def label(self) -> str:
        return f'ThresholdInventoryPolicy(threshold={self.threshold_grams}g)'
