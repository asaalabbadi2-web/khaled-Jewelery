"""InventoryHealthReport — admin dashboard metrics for the inventory engine.

Not used at runtime for business logic.  Used by:
  - Admin dashboard endpoint
  - Support / debugging
  - Pre-upgrade audits

Call InventoryHealthReport.build() inside an app context.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import List


@dataclass
class HealthMetric:
    key:         str
    label:       str
    value:       object   # int | float | str | None
    ok:          bool     # True = healthy, False = needs attention
    detail:      str = ''


@dataclass
class InventoryHealthSnapshot:
    generated_at:  datetime
    metrics:       List[HealthMetric] = field(default_factory=list)

    @property
    def has_issues(self) -> bool:
        return any(not m.ok for m in self.metrics)

    def to_dict(self) -> dict:
        return {
            'generated_at': self.generated_at.isoformat(),
            'has_issues':   self.has_issues,
            'metrics': [
                {
                    'key':    m.key,
                    'label':  m.label,
                    'value':  m.value,
                    'ok':     m.ok,
                    'detail': m.detail,
                }
                for m in self.metrics
            ],
        }


class InventoryHealthReport:

    @classmethod
    def build(cls) -> InventoryHealthSnapshot:
        from services.inventory_invariant_checker import BalanceInvariantChecker
        from models import (
            InventoryLedger, InventoryBalance,
            InventoryCountSession, InventoryAdjustment,
        )
        from sqlalchemy import func

        snap = InventoryHealthSnapshot(generated_at=datetime.now())  # clock-guard: TIME-001
        add = snap.metrics.append

        # 1. Balance invariant
        violations = BalanceInvariantChecker.check_all()
        add(HealthMetric(
            key='invariant_violations',
            label='Buckets with balance mismatch',
            value=len(violations),
            ok=len(violations) == 0,
            detail=(
                'BalanceInvariantChecker found no drift' if not violations
                else f'{len(violations)} bucket(s) diverge between Ledger and Balance'
            ),
        ))

        # 2. Open count sessions
        open_sessions = InventoryCountSession.query.filter(
            InventoryCountSession.status.in_(['open', 'counting'])
        ).count()
        add(HealthMetric(
            key='open_count_sessions',
            label='Open count sessions',
            value=open_sessions,
            ok=True,
            detail=f'{open_sessions} session(s) currently open',
        ))

        # 3. Pending (draft) adjustments
        pending_adj = InventoryAdjustment.query.filter_by(status='draft').count()
        add(HealthMetric(
            key='pending_adjustments',
            label='Pending (unposted) adjustments',
            value=pending_adj,
            ok=pending_adj == 0,
            detail=(
                'No unposted adjustments' if pending_adj == 0
                else f'{pending_adj} adjustment(s) in draft — not yet posted to Ledger'
            ),
        ))

        # 4. Last count session
        last_session = (
            InventoryCountSession.query
            .filter(InventoryCountSession.status == 'approved')
            .order_by(InventoryCountSession.approved_at.desc())
            .first()
        )
        if last_session:
            last_snap_label = last_session.approved_at.isoformat() if last_session.approved_at else '—'
            add(HealthMetric(
                key='last_inventory_snapshot',
                label='Last approved count session',
                value=last_snap_label,
                ok=True,
                detail=f'Session #{last_session.id}',
            ))
        else:
            add(HealthMetric(
                key='last_inventory_snapshot',
                label='Last approved count session',
                value=None,
                ok=True,
                detail='No approved count session yet',
            ))

        # 5. Ledger row count
        ledger_count = InventoryLedger.query.count()
        add(HealthMetric(
            key='ledger_row_count',
            label='Total Ledger rows',
            value=ledger_count,
            ok=True,
            detail=f'{ledger_count} inventory movement rows',
        ))

        # 6. Balance bucket count
        bucket_count = InventoryBalance.query.count()
        add(HealthMetric(
            key='balance_bucket_count',
            label='Active inventory buckets',
            value=bucket_count,
            ok=True,
            detail=f'{bucket_count} (branch × category × karat) buckets tracked',
        ))

        # 7. Ledger max id (last posted entry)
        max_ledger_id = (
            InventoryLedger.query
            .with_entities(func.max(InventoryLedger.id))
            .scalar()
        )
        add(HealthMetric(
            key='ledger_max_id',
            label='Latest Ledger entry ID',
            value=max_ledger_id,
            ok=True,
        ))

        return snap
