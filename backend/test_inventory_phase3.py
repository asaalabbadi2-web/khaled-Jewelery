"""Tests for Phase 3: BalanceInvariantChecker + InventoryCountService.

Covers:
  InvariantChecker:
    - Clean state passes assert_clean()
    - Artificially broken balance is detected
    - Ledger bucket without Balance row is detected

  Session lifecycle:
    - open_session() captures snapshot_ledger_id correctly
    - Double open on same branch is rejected
    - populate_lines() creates one line per Balance bucket
    - populate_lines() is idempotent
    - expected_weight + expected_ledger_id frozen at snapshot time
    - record_count() computes variance
    - close_session() requires all lines counted
    - approve_session() requires closed status
    - Full happy-path: open → populate → count → close → approve

  Snapshot isolation:
    - Entries posted AFTER session open are excluded from expected_weight
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
)
from services.inventory_posting_service import InventoryPostingService
from services.inventory_count_service import InventoryCountService
from services.inventory_invariant_checker import BalanceInvariantChecker

_id_seq = itertools.count(400_000)


def _uid(prefix: str = 'x') -> str:
    return f'{prefix}-{uuid.uuid4().hex[:6]}'


def _branch() -> Branch:
    b = Branch(name=_uid('فرع'), branch_code=_uid('BR'))
    db.session.add(b)
    db.session.flush()
    return b


def _category() -> Category:
    c = Category(name=_uid('تصنيف'))
    db.session.add(c)
    db.session.flush()
    return c


def _post_invoice(invoice_type: str, branch_id, cat_id, karat: float, weight: float) -> Invoice:
    inv = Invoice(
        invoice_type_id=next(_id_seq),
        invoice_type=invoice_type,
        date=datetime.now(),
        total=0.0,
        is_posted=True,
        posted_by='test',
        branch_id=branch_id,
    )
    db.session.add(inv)
    db.session.flush()
    item = InvoiceItem(
        invoice_id=inv.id, quantity=1, price=0.0,
        karat=karat, weight=weight, category_id=cat_id,
    )
    db.session.add(item)
    db.session.flush()
    db.session.refresh(inv)
    InventoryPostingService.post(inv)
    db.session.flush()
    return inv


# ── BalanceInvariantChecker ───────────────────────────────────────────────────

class TestBalanceInvariantChecker:

    def test_clean_state_passes(self):
        with app.app_context():
            cat = _category()
            br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 10.0)

            # Should not raise
            BalanceInvariantChecker.assert_clean()
            db.session.rollback()

    def test_broken_balance_is_detected(self):
        with app.app_context():
            cat = _category()
            br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 10.0)

            # Tamper with balance directly (simulates a bug bypassing the service)
            bal = InventoryBalance.query.filter_by(
                branch_id=br.id, category_id=cat.id, karat=21.0
            ).first()
            assert bal is not None
            bal.balance = 999.0  # wrong!
            db.session.flush()

            violations = BalanceInvariantChecker.check_all()
            assert any(
                v.branch_id == br.id and v.category_id == cat.id and v.karat == 21.0
                for v in violations
            )
            db.session.rollback()

    def test_assert_clean_raises_on_violation(self):
        with app.app_context():
            cat = _category()
            br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 5.0)

            bal = InventoryBalance.query.filter_by(
                branch_id=br.id, category_id=cat.id, karat=21.0
            ).first()
            bal.balance = 0.0  # wrong!
            db.session.flush()

            with pytest.raises(AssertionError, match='violation'):
                BalanceInvariantChecker.assert_clean()
            db.session.rollback()

    def test_ledger_without_balance_is_detected(self):
        """If a Ledger entry exists with no matching Balance row, flag it."""
        with app.app_context():
            cat = _category()
            br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 7.0)

            # Remove the balance row to simulate missing projection
            InventoryBalance.query.filter_by(
                branch_id=br.id, category_id=cat.id, karat=21.0
            ).delete()
            db.session.flush()

            violations = BalanceInvariantChecker.check_all()
            assert any(
                v.branch_id == br.id and v.category_id == cat.id
                for v in violations
            )
            db.session.rollback()


# ── Session Lifecycle ─────────────────────────────────────────────────────────

class TestSessionLifecycle:

    def test_open_captures_snapshot_ledger_id(self):
        with app.app_context():
            cat = _category()
            br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 10.0)

            from models import InventoryLedger
            from sqlalchemy import func
            max_id = db.session.query(func.max(InventoryLedger.id)).scalar()

            session = InventoryCountService.open_session(br.id, opened_by='مدير المخزن')
            assert session.snapshot_ledger_id == max_id
            assert session.status == 'open'
            db.session.rollback()

    def test_double_open_same_branch_rejected(self):
        with app.app_context():
            br = _branch()
            InventoryCountService.open_session(br.id, opened_by='مدير')
            db.session.flush()

            with pytest.raises(ValueError, match='جلسة جرد مفتوحة'):
                InventoryCountService.open_session(br.id, opened_by='مدير 2')
            db.session.rollback()

    def test_populate_lines_creates_one_per_bucket(self):
        with app.app_context():
            cat1 = _category()
            cat2 = _category()
            br = _branch()
            _post_invoice('شراء', br.id, cat1.id, 18.0, 10.0)
            _post_invoice('شراء', br.id, cat2.id, 21.0, 20.0)

            session = InventoryCountService.open_session(br.id, opened_by='مدير')
            db.session.flush()

            lines = InventoryCountService.populate_lines(session)
            assert len(lines) == 2

            cats = {ln.category_id for ln in lines}
            assert cat1.id in cats
            assert cat2.id in cats
            db.session.rollback()

    def test_populate_lines_is_idempotent(self):
        with app.app_context():
            cat = _category()
            br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 5.0)

            session = InventoryCountService.open_session(br.id, opened_by='مدير')
            db.session.flush()

            InventoryCountService.populate_lines(session)
            db.session.flush()
            second = InventoryCountService.populate_lines(session)

            assert second == []  # no new lines created
            total = InventoryCountLine.query.filter_by(session_id=session.id).count()
            assert total == 1
            db.session.rollback()

    def test_expected_weight_and_ledger_id_frozen_at_open(self):
        """Entries posted after open do NOT affect expected_weight."""
        with app.app_context():
            cat = _category()
            br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 30.0)

            session = InventoryCountService.open_session(br.id, opened_by='مدير')
            db.session.flush()
            lines = InventoryCountService.populate_lines(session)
            db.session.flush()

            line = lines[0]
            frozen_expected = line.expected_weight
            frozen_ledger_id = line.expected_ledger_id

            # Post more after session open
            _post_invoice('شراء', br.id, cat.id, 21.0, 100.0)

            # Reload — expected values must NOT have changed
            db.session.refresh(line)
            assert line.expected_weight == pytest.approx(frozen_expected)
            assert line.expected_ledger_id == frozen_ledger_id
            db.session.rollback()

    def test_record_count_computes_variance(self):
        with app.app_context():
            cat = _category()
            br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 50.0)

            session = InventoryCountService.open_session(br.id, opened_by='مدير')
            db.session.flush()
            InventoryCountService.populate_lines(session)
            db.session.flush()

            line = InventoryCountService.record_count(
                session, category_id=cat.id, karat=21.0,
                counted_weight=48.0, counted_by='أمين المخزن'
            )

            assert line.counted_weight == pytest.approx(48.0)
            assert line.variance == pytest.approx(-2.0)  # shortage
            assert session.status == 'counting'
            db.session.rollback()

    def test_close_blocked_if_uncounted_lines(self):
        with app.app_context():
            cat = _category()
            br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 10.0)

            session = InventoryCountService.open_session(br.id, opened_by='مدير')
            db.session.flush()
            InventoryCountService.populate_lines(session)
            db.session.flush()

            # Don't call record_count → line still has counted_weight=None
            with pytest.raises(ValueError, match='لم يُعدّ'):
                InventoryCountService.close_session(session)
            db.session.rollback()

    def test_approve_blocked_if_not_closed(self):
        with app.app_context():
            br = _branch()
            session = InventoryCountService.open_session(br.id, opened_by='مدير')
            db.session.flush()

            with pytest.raises(ValueError, match='إغلاق|إغلاق'):
                InventoryCountService.approve_session(session, approved_by='المدير العام')
            db.session.rollback()

    def test_full_happy_path(self):
        """open → populate → count → close → approve."""
        with app.app_context():
            cat1 = _category()
            cat2 = _category()
            br = _branch()
            _post_invoice('شراء', br.id, cat1.id, 21.0, 100.0)
            _post_invoice('شراء', br.id, cat2.id, 18.0, 60.0)

            # Open
            session = InventoryCountService.open_session(br.id, opened_by='مدير المخزن')
            db.session.flush()
            assert session.status == 'open'

            # Populate
            lines = InventoryCountService.populate_lines(session)
            db.session.flush()
            assert len(lines) == 2

            # Count both lines
            InventoryCountService.record_count(session, cat1.id, 21.0, 98.0, 'أمين المخزن')
            InventoryCountService.record_count(session, cat2.id, 18.0, 61.5, 'أمين المخزن')
            db.session.flush()
            assert session.status == 'counting'

            # Close
            InventoryCountService.close_session(session)
            db.session.flush()
            assert session.status == 'closed'
            assert session.closed_at is not None

            # Approve
            session, _ = InventoryCountService.approve_session(session, approved_by='المدير العام')
            db.session.flush()
            assert session.status == 'approved'
            assert session.approved_by == 'المدير العام'

            # Verify variances
            l1 = InventoryCountLine.query.filter_by(session_id=session.id, category_id=cat1.id).first()
            l2 = InventoryCountLine.query.filter_by(session_id=session.id, category_id=cat2.id).first()
            assert l1.variance == pytest.approx(-2.0)   # shortage
            assert l2.variance == pytest.approx(+1.5)   # surplus

            # Invariant must still hold
            BalanceInvariantChecker.assert_clean()
            db.session.rollback()
