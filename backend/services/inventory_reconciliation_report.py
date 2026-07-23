"""InventoryReconciliationReport — four-way reconciliation for auditors.

Compares four independent sources for each inventory bucket:

    ┌─────────────────────┬──────────────────────────────────────────────┐
    │  Source             │  How computed                                │
    ├─────────────────────┼──────────────────────────────────────────────┤
    │  InventoryLedger    │  SUM(weight_delta) — source of truth         │
    │  InventoryBalance   │  Cached projection — updated per transaction │
    │  Physical Count     │  Last approved count session per bucket      │
    │  GL (Phase 5)       │  Weight balance on gold inventory accounts   │
    └─────────────────────┴──────────────────────────────────────────────┘

If any two values diverge beyond TOLERANCE, the bucket is flagged.

Usage:
    report = InventoryReconciliationReport.build()
    for r in report.mismatches:
        print(r)

The GL column is None until Phase 5 wires real Account balances.
The Physical Count column is None for buckets never counted.

Run this report:
  - Before any major upgrade
  - As a monthly audit procedure
  - Whenever BalanceInvariantChecker.check_all() returns violations
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


TOLERANCE = 1e-4  # grams


@dataclass
class ReconciliationRow:
    branch_id:    Optional[int]
    category_id:  Optional[int]
    karat:        float

    # ── Source 1: InventoryLedger ──────────────────────────────────────────
    ledger_sum:   float          # SUM(InventoryLedger.weight_delta)

    # ── Source 2: InventoryBalance ─────────────────────────────────────────
    balance:      float          # InventoryBalance.balance

    # ── Source 3: Physical Count ───────────────────────────────────────────
    last_count_session_id: Optional[int]    # ID of last approved count session
    last_count_at:         Optional[datetime]  # session.approved_at
    last_count_weight:     Optional[float]  # line.counted_weight at approval
    last_count_variance:   Optional[float]  # counted_weight - expected_weight

    # ── Source 4: GL (Phase 5) ─────────────────────────────────────────────
    gl_weight:    Optional[float]  # GL account weight balance (Phase 5)

    # ── Cross-checks ──────────────────────────────────────────────────────
    ledger_vs_balance_ok: bool
    ledger_vs_gl_ok:      Optional[bool]  # None = GL not yet available

    @property
    def count_available(self) -> bool:
        return self.last_count_weight is not None

    @property
    def ledger_vs_count_ok(self) -> Optional[bool]:
        """True if last physical count matches current ledger sum.

        None = no count data available for this bucket.
        Note: a mismatch here is expected if movements occurred after the
        count session — it indicates the ledger has moved since last count,
        not necessarily an error.
        """
        if self.last_count_weight is None:
            return None
        return abs(self.ledger_sum - self.last_count_weight) <= TOLERANCE

    @property
    def has_mismatch(self) -> bool:
        if not self.ledger_vs_balance_ok:
            return True
        if self.ledger_vs_gl_ok is False:
            return True
        return False

    def to_dict(self) -> dict:
        return {
            'branch_id':              self.branch_id,
            'category_id':            self.category_id,
            'karat':                  self.karat,
            'ledger_sum':             self.ledger_sum,
            'balance':                self.balance,
            'last_count_session_id':  self.last_count_session_id,
            'last_count_at':          self.last_count_at.isoformat() if self.last_count_at else None,
            'last_count_weight':      self.last_count_weight,
            'last_count_variance':    self.last_count_variance,
            'ledger_vs_count_ok':     self.ledger_vs_count_ok,
            'gl_weight':              self.gl_weight,
            'ledger_vs_balance_ok':   self.ledger_vs_balance_ok,
            'ledger_vs_gl_ok':        self.ledger_vs_gl_ok,
            'has_mismatch':           self.has_mismatch,
        }


@dataclass
class ReconciliationSnapshot:
    generated_at: datetime
    gl_available: bool
    rows:         List[ReconciliationRow] = field(default_factory=list)

    @property
    def mismatches(self) -> List[ReconciliationRow]:
        return [r for r in self.rows if r.has_mismatch]

    @property
    def is_clean(self) -> bool:
        return len(self.mismatches) == 0

    @property
    def count_drift_buckets(self) -> List[ReconciliationRow]:
        """Buckets where ledger has moved since last physical count.

        These are not errors — they are normal movements post-count.
        Useful for scheduling the next count: buckets with the largest
        drift are the most overdue for re-counting.
        """
        return [
            r for r in self.rows
            if r.count_available and r.ledger_vs_count_ok is False
        ]

    def to_dict(self) -> dict:
        return {
            'generated_at':         self.generated_at.isoformat(),
            'gl_available':         self.gl_available,
            'total_buckets':        len(self.rows),
            'mismatches':           len(self.mismatches),
            'is_clean':             self.is_clean,
            'count_drift_buckets':  len(self.count_drift_buckets),
            'rows':                 [r.to_dict() for r in self.rows],
        }


class InventoryReconciliationReport:

    @classmethod
    def build(cls) -> ReconciliationSnapshot:
        from models import (
            InventoryLedger, InventoryBalance,
            InventoryCountSession, InventoryCountLine,
        )
        from sqlalchemy import func

        snap = ReconciliationSnapshot(
            generated_at=datetime.now(),  # clock-guard: TIME-001
            gl_available=False,  # Phase 5 sets this True when GL wired
        )

        # ── Step 1: Ledger sums per bucket ────────────────────────────────────
        ledger_rows = (
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
        ledger_map: dict[tuple, float] = {
            (r.branch_id, r.category_id, r.karat): round(float(r.total or 0.0), 4)
            for r in ledger_rows
        }

        # ── Step 2: Balance per bucket ────────────────────────────────────────
        balance_map: dict[tuple, float] = {
            (b.branch_id, b.category_id, b.karat): round(float(b.balance or 0.0), 4)
            for b in InventoryBalance.query.all()
        }

        # ── Step 3: Physical Count — last approved session per bucket ─────────
        # For each (branch_id, category_id, karat) bucket, find the most recent
        # approved InventoryCountSession that has a counted line for that bucket.
        # We join InventoryCountLine → InventoryCountSession and take MAX session id
        # as a proxy for "most recent" (IDs are monotonic).
        count_map: dict[tuple, dict] = cls._build_count_map(
            InventoryCountSession, InventoryCountLine
        )

        # ── Step 4: GL per bucket (Phase 5 placeholder) ───────────────────────
        gl_map: dict[tuple, Optional[float]] = {}
        # Phase 5:
        #   gl_map = InventoryAccountingService.get_gl_weight_per_bucket()
        #   snap.gl_available = True

        # ── Step 5: Union of all known buckets ────────────────────────────────
        all_buckets = set(ledger_map.keys()) | set(balance_map.keys())

        for bucket in sorted(all_buckets, key=lambda b: (b[0] or 0, b[1] or 0, b[2])):
            br, cat, karat = bucket
            ledger_val  = ledger_map.get(bucket, 0.0)
            balance_val = balance_map.get(bucket, 0.0)
            gl_val      = gl_map.get(bucket)
            count_data  = count_map.get(bucket, {})

            l_vs_b = abs(ledger_val - balance_val) <= TOLERANCE
            l_vs_gl = (
                abs(ledger_val - gl_val) <= TOLERANCE
                if gl_val is not None else None
            )

            snap.rows.append(ReconciliationRow(
                branch_id=br,
                category_id=cat,
                karat=karat,
                ledger_sum=ledger_val,
                balance=balance_val,
                last_count_session_id=count_data.get('session_id'),
                last_count_at=count_data.get('approved_at'),
                last_count_weight=count_data.get('counted_weight'),
                last_count_variance=count_data.get('variance'),
                gl_weight=gl_val,
                ledger_vs_balance_ok=l_vs_b,
                ledger_vs_gl_ok=l_vs_gl,
            ))

        return snap

    @classmethod
    def _build_count_map(cls, CountSession, CountLine) -> dict[tuple, dict]:
        """Return the most recent approved count data per bucket.

        Strategy: query all approved session lines ordered by session_id DESC,
        keep only the first hit per (branch_id, category_id, karat).
        This avoids a complex MAX subquery and works for all DB backends.
        """
        lines = (
            CountLine.query
            .join(CountSession, CountLine.session_id == CountSession.id)
            .filter(
                CountSession.status == 'approved',
                CountLine.counted_weight.isnot(None),
            )
            .order_by(CountLine.session_id.desc())
            .with_entities(
                CountLine.branch_id,
                CountLine.category_id,
                CountLine.karat,
                CountLine.counted_weight,
                CountLine.variance,
                CountLine.session_id,
                CountSession.approved_at,
            )
            .all()
        )

        result: dict[tuple, dict] = {}
        for line in lines:
            key = (line.branch_id, line.category_id, line.karat)
            if key not in result:
                result[key] = {
                    'session_id':    line.session_id,
                    'approved_at':   line.approved_at,
                    'counted_weight': round(float(line.counted_weight or 0.0), 4),
                    'variance':       round(float(line.variance or 0.0), 4)
                    if line.variance is not None else None,
                }
        return result
