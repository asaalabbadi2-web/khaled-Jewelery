"""BalanceInvariantChecker — verification tool for the Inventory Projection.

Not used at runtime.  Run it:
  - In tests (after every post/reverse)
  - As an admin command before major upgrades
  - As a scheduled audit to catch drift

The invariant:
    InventoryBalance.balance  ==  SUM(InventoryLedger.weight_delta)
    for every bucket (branch_id, category_id, karat)

A violation means a bug introduced a write to InventoryLedger that bypassed
InventoryPostingService, or a balance row was modified directly.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List


@dataclass
class BalanceViolation:
    branch_id:    object  # int | None
    category_id:  object  # int | None
    karat:        float
    ledger_sum:   float  # what the Ledger says
    balance:      float  # what InventoryBalance says
    delta:        float  # ledger_sum - balance  (non-zero = violation)
    balance_id:   int


class BalanceInvariantChecker:

    TOLERANCE = 1e-4  # grams — float rounding allowance

    @classmethod
    def check_all(cls) -> List[BalanceViolation]:
        """Return all buckets where Balance diverges from Ledger sum.

        Empty list means the invariant holds everywhere.
        """
        from models import InventoryBalance, InventoryLedger
        from sqlalchemy import func

        violations: List[BalanceViolation] = []

        # Compute ledger sums per bucket in one query
        ledger_sums: dict[tuple, float] = {}
        rows = (
            InventoryLedger.query
            .with_entities(
                InventoryLedger.branch_id,
                InventoryLedger.category_id,
                InventoryLedger.karat,
                func.sum(InventoryLedger.weight_delta).label('total'),
            )
            .group_by(
                InventoryLedger.branch_id,
                InventoryLedger.category_id,
                InventoryLedger.karat,
            )
            .all()
        )
        for r in rows:
            ledger_sums[(r.branch_id, r.category_id, r.karat)] = float(r.total or 0.0)

        # Compare against every InventoryBalance row
        for bal in InventoryBalance.query.all():
            key = (bal.branch_id, bal.category_id, bal.karat)
            ledger_val = round(ledger_sums.get(key, 0.0), 4)
            balance_val = round(float(bal.balance or 0.0), 4)
            diff = round(ledger_val - balance_val, 6)
            if abs(diff) > cls.TOLERANCE:
                violations.append(BalanceViolation(
                    branch_id=bal.branch_id,
                    category_id=bal.category_id,
                    karat=bal.karat,
                    ledger_sum=ledger_val,
                    balance=balance_val,
                    delta=diff,
                    balance_id=bal.id,
                ))

        # Also flag buckets that exist in Ledger but have no Balance row
        balance_keys = {
            (b.branch_id, b.category_id, b.karat)
            for b in InventoryBalance.query.all()
        }
        for (br, cat, karat), total in ledger_sums.items():
            if (br, cat, karat) not in balance_keys:
                violations.append(BalanceViolation(
                    branch_id=br,
                    category_id=cat,
                    karat=karat,
                    ledger_sum=round(total, 4),
                    balance=0.0,
                    delta=round(total, 4),
                    balance_id=-1,  # sentinel: no Balance row exists
                ))

        return violations

    @classmethod
    def assert_clean(cls) -> None:
        """Raise AssertionError if any violation is found.

        Intended for use in tests and CI:
            BalanceInvariantChecker.assert_clean()
        """
        violations = cls.check_all()
        if violations:
            lines = []
            for v in violations:
                lines.append(
                    f"  bucket=({v.branch_id}, {v.category_id}, {v.karat}g) "
                    f"ledger={v.ledger_sum} balance={v.balance} Δ={v.delta}"
                )
            raise AssertionError(
                f"BalanceInvariantChecker: {len(violations)} violation(s):\n"
                + "\n".join(lines)
            )
