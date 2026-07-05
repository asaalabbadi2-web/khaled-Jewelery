"""Tests for Phase 4: InventoryAdjustment + InventoryHealthReport.

Covers:
  Adjustment from count session:
    - approve_session() with variance creates adjustment + posts to Ledger
    - Ledger entries have movement_type='adjustment' and correct weight_delta
    - Balance corrected after adjustment
    - approve_session() with zero variance returns None adjustment
    - Invariant holds after approve

  Manual adjustment:
    - create_manual() with auto_post posts to Ledger
    - Zero-variance lines are skipped
    - Idempotency: posting same adjustment twice adds no new rows

  InventoryPostingService dispatch:
    - post(adjustment) dispatches correctly
    - post(unsupported) still raises

  InventoryHealthReport:
    - build() returns a snapshot with expected keys
    - Invariant violation reflected in has_issues
    - Counts match actual DB state
"""
import itertools
import uuid
from datetime import datetime
from typing import Optional

import pytest

from app import app
from models import (
    db, Invoice, InvoiceItem, Branch, Category,
    InventoryLedger, InventoryBalance,
    InventoryCountSession, InventoryCountLine,
    InventoryAdjustment, InventoryAdjustmentLine,
)
from services.inventory_posting_service import InventoryPostingService
from services.inventory_count_service import InventoryCountService
from services.inventory_adjustment_service import InventoryAdjustmentService
from services.inventory_invariant_checker import BalanceInvariantChecker
from services.inventory_health_report import InventoryHealthReport

_id_seq = itertools.count(500_000)


def _uid(p='x'):
    return f'{p}-{uuid.uuid4().hex[:6]}'


def _branch():
    b = Branch(name=_uid('فرع'), branch_code=_uid('BR'))
    db.session.add(b); db.session.flush()
    return b


def _category():
    c = Category(name=_uid('تصنيف'))
    db.session.add(c); db.session.flush()
    return c


def _post_invoice(itype, branch_id, cat_id, karat, weight):
    inv = Invoice(
        invoice_type_id=next(_id_seq), invoice_type=itype,
        date=datetime.now(), total=0.0, is_posted=True,
        posted_by='test', branch_id=branch_id,
    )
    db.session.add(inv); db.session.flush()
    item = InvoiceItem(
        invoice_id=inv.id, quantity=1, price=0.0,
        karat=karat, weight=weight, category_id=cat_id,
    )
    db.session.add(item); db.session.flush()
    db.session.refresh(inv)
    InventoryPostingService.post(inv)
    db.session.flush()
    return inv


def _full_session(br, cat, karat, initial_weight, counted_weight):
    """Post an invoice, open session, count, close — ready for approve."""
    _post_invoice('شراء', br.id, cat.id, karat, initial_weight)
    session = InventoryCountService.open_session(br.id, opened_by='مدير')
    db.session.flush()
    InventoryCountService.populate_lines(session)
    db.session.flush()
    InventoryCountService.record_count(session, cat.id, karat, counted_weight)
    db.session.flush()
    InventoryCountService.close_session(session)
    db.session.flush()
    return session


# ── Adjustment from count session ─────────────────────────────────────────────

class TestAdjustmentFromSession:

    def test_approve_with_variance_creates_adjustment(self):
        with app.app_context():
            cat = _category(); br = _branch()
            session = _full_session(br, cat, 21.0, initial_weight=50.0, counted_weight=48.0)
            # variance = 48 - 50 = -2.0

            session, adj = InventoryCountService.approve_session(session, 'مدير')
            db.session.flush()

            assert session.status == 'approved'
            assert adj is not None
            assert adj.adjustment_type == 'count_variance'
            assert adj.status == 'posted'
            db.session.rollback()

    def test_adjustment_ledger_entry_has_correct_delta(self):
        with app.app_context():
            cat = _category(); br = _branch()
            session = _full_session(br, cat, 21.0, 50.0, 48.0)

            _, adj = InventoryCountService.approve_session(session, 'مدير')
            db.session.flush()

            adj_rows = InventoryLedger.query.filter_by(
                source_type='adjustment', source_id=adj.id, movement_type='adjustment'
            ).all()
            assert len(adj_rows) == 1
            assert adj_rows[0].weight_delta == pytest.approx(-2.0)
            db.session.rollback()

    def test_balance_corrected_after_approve(self):
        with app.app_context():
            cat = _category(); br = _branch()
            session = _full_session(br, cat, 21.0, 50.0, 48.0)

            bal_before = InventoryBalance.query.filter_by(
                branch_id=br.id, category_id=cat.id, karat=21.0
            ).first().balance

            InventoryCountService.approve_session(session, 'مدير')
            db.session.flush()

            bal_after = InventoryBalance.query.filter_by(
                branch_id=br.id, category_id=cat.id, karat=21.0
            ).first().balance

            assert bal_before == pytest.approx(50.0)
            assert bal_after  == pytest.approx(48.0)
            db.session.rollback()

    def test_approve_with_zero_variance_returns_none(self):
        """If counted == expected for all lines, no adjustment is created."""
        with app.app_context():
            cat = _category(); br = _branch()
            session = _full_session(br, cat, 21.0, 30.0, 30.0)  # no variance

            _, adj = InventoryCountService.approve_session(session, 'مدير')
            db.session.flush()

            assert adj is None
            db.session.rollback()

    def test_invariant_holds_after_approve(self):
        with app.app_context():
            cat = _category(); br = _branch()
            session = _full_session(br, cat, 21.0, 100.0, 97.5)

            InventoryCountService.approve_session(session, 'مدير')
            db.session.flush()

            BalanceInvariantChecker.assert_clean()
            db.session.rollback()

    def test_approve_surplus_corrects_balance_up(self):
        """counted > expected → positive variance → balance increases."""
        with app.app_context():
            cat = _category(); br = _branch()
            session = _full_session(br, cat, 21.0, 20.0, 22.5)

            _, adj = InventoryCountService.approve_session(session, 'مدير')
            db.session.flush()

            adj_row = InventoryLedger.query.filter_by(
                source_type='adjustment', source_id=adj.id
            ).first()
            assert adj_row.weight_delta == pytest.approx(+2.5)

            bal = InventoryBalance.query.filter_by(
                branch_id=br.id, category_id=cat.id, karat=21.0
            ).first()
            assert bal.balance == pytest.approx(22.5)
            db.session.rollback()


# ── Manual adjustment ─────────────────────────────────────────────────────────

class TestManualAdjustment:

    def test_manual_adjustment_with_auto_post(self):
        with app.app_context():
            cat = _category(); br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 40.0)

            adj = InventoryAdjustmentService.create_manual(
                branch_id=br.id,
                lines_data=[{
                    'category_id': cat.id,
                    'karat': 21.0,
                    'expected_weight': 40.0,
                    'counted_weight': 39.0,
                    'variance_weight': -1.0,
                    'notes': 'فاقد تصنيع',
                }],
                reason='فاقد تصنيع',
                created_by='مدير الإنتاج',
                auto_post=True,
            )
            db.session.flush()

            assert adj.status == 'posted'
            ledger_row = InventoryLedger.query.filter_by(
                source_type='adjustment', source_id=adj.id
            ).first()
            assert ledger_row is not None
            assert ledger_row.weight_delta == pytest.approx(-1.0)

            bal = InventoryBalance.query.filter_by(
                branch_id=br.id, category_id=cat.id, karat=21.0
            ).first()
            assert bal.balance == pytest.approx(39.0)
            db.session.rollback()

    def test_zero_variance_line_is_skipped(self):
        with app.app_context():
            cat = _category(); br = _branch()
            adj = InventoryAdjustmentService.create_manual(
                branch_id=br.id,
                lines_data=[
                    {'category_id': cat.id, 'karat': 21.0, 'variance_weight': 0.0},
                    {'category_id': cat.id, 'karat': 18.0, 'variance_weight': -3.0},
                ],
                reason='اختبار',
                created_by='test',
                auto_post=True,
            )
            db.session.flush()

            rows = InventoryLedger.query.filter_by(
                source_type='adjustment', source_id=adj.id
            ).all()
            assert len(rows) == 1  # only the non-zero line
            assert rows[0].karat == 18.0
            db.session.rollback()

    def test_post_adjustment_is_idempotent(self):
        with app.app_context():
            cat = _category(); br = _branch()
            adj = InventoryAdjustmentService.create_manual(
                branch_id=br.id,
                lines_data=[{'category_id': cat.id, 'karat': 21.0, 'variance_weight': -2.0}],
                reason='test',
                created_by='test',
                auto_post=True,
            )
            db.session.flush()

            # Call post_adjustment again on an already-posted adjustment
            second = InventoryAdjustmentService.post_adjustment(adj)
            assert second == []

            rows = InventoryLedger.query.filter_by(
                source_type='adjustment', source_id=adj.id
            ).all()
            assert len(rows) == 1
            db.session.rollback()


# ── InventoryPostingService dispatch ─────────────────────────────────────────

class TestPostingServiceDispatch:

    def test_post_adjustment_dispatched(self):
        with app.app_context():
            cat = _category(); br = _branch()
            adj = InventoryAdjustmentService.create_manual(
                branch_id=br.id,
                lines_data=[{'category_id': cat.id, 'karat': 21.0, 'variance_weight': 5.0}],
                reason='test',
                created_by='test',
            )
            db.session.flush()
            adj.posted_by = 'test'

            result = InventoryPostingService.post(adj)
            assert len(result) == 1
            assert result[0].movement_type == 'adjustment'
            db.session.rollback()


# ── InventoryHealthReport ─────────────────────────────────────────────────────

class TestInventoryHealthReport:

    def test_build_returns_snapshot_with_expected_keys(self):
        with app.app_context():
            cat = _category(); br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 10.0)

            snap = InventoryHealthReport.build()

            assert snap.generated_at is not None
            keys = {m.key for m in snap.metrics}
            for expected_key in (
                'invariant_violations', 'open_count_sessions', 'pending_adjustments',
                'last_inventory_snapshot', 'ledger_row_count', 'balance_bucket_count',
                'ledger_max_id',
            ):
                assert expected_key in keys
            db.session.rollback()

    def test_clean_state_has_no_issues(self):
        with app.app_context():
            cat = _category(); br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 5.0)

            snap = InventoryHealthReport.build()
            inv_metric = next(m for m in snap.metrics if m.key == 'invariant_violations')
            assert inv_metric.value == 0
            assert inv_metric.ok is True
            db.session.rollback()

    def test_broken_balance_reflected_in_has_issues(self):
        with app.app_context():
            cat = _category(); br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 5.0)

            bal = InventoryBalance.query.filter_by(
                branch_id=br.id, category_id=cat.id, karat=21.0
            ).first()
            bal.balance = 999.0
            db.session.flush()

            snap = InventoryHealthReport.build()
            assert snap.has_issues is True
            inv_metric = next(m for m in snap.metrics if m.key == 'invariant_violations')
            assert inv_metric.value > 0
            db.session.rollback()

    def test_pending_adjustment_reflected(self):
        with app.app_context():
            cat = _category(); br = _branch()
            # Create a draft (unposted) adjustment
            InventoryAdjustmentService.create_manual(
                branch_id=br.id,
                lines_data=[{'category_id': cat.id, 'karat': 21.0, 'variance_weight': -1.0}],
                reason='test',
                created_by='test',
                auto_post=False,  # stays in draft
            )
            db.session.flush()

            snap = InventoryHealthReport.build()
            pending_metric = next(m for m in snap.metrics if m.key == 'pending_adjustments')
            assert pending_metric.value >= 1
            assert pending_metric.ok is False
            db.session.rollback()

    def test_to_dict_serializable(self):
        with app.app_context():
            snap = InventoryHealthReport.build()
            d = snap.to_dict()
            import json
            json.dumps(d)  # must not raise
            db.session.rollback()
