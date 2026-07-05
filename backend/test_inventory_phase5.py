"""Tests for Phase 5 foundations: InventoryAccountingService + ReconciliationReport.

Covers:
  InventoryAccountingService:
    - GL layer is separate from AdjustmentService (no direct JE creation in adj)
    - post_adjustment_to_gl() accepts an adjustment without raising
    - Full adjustment flow still passes invariant

  InventoryReconciliationReport:
    - Clean state: all buckets show ledger_vs_balance_ok=True
    - Mismatch detected when balance is tampered
    - Report covers all buckets from both Ledger and Balance
    - to_dict() is JSON-serialisable
    - gl_available=False until Phase 5 wires GL
    - Missing Balance bucket (Ledger-only) is flagged
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
from services.inventory_accounting_service import InventoryAccountingService
from services.inventory_adjustment_service import InventoryAdjustmentService
from services.inventory_count_service import InventoryCountService
from services.inventory_reconciliation_report import InventoryReconciliationReport
from services.inventory_invariant_checker import BalanceInvariantChecker

_id_seq = itertools.count(600_000)


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


# ── InventoryAccountingService ────────────────────────────────────────────────

class TestInventoryAccountingService:

    def test_post_adjustment_to_gl_does_not_raise(self):
        """Phase 5 stub must accept a valid adjustment without error."""
        with app.app_context():
            cat = _category(); br = _branch()
            adj = InventoryAdjustmentService.create_manual(
                branch_id=br.id,
                lines_data=[{
                    'category_id': cat.id, 'karat': 21.0,
                    'variance_weight': -1.5,
                }],
                reason='test',
                created_by='test',
                auto_post=True,
            )
            db.session.flush()

            # Should not raise — stub logs and returns
            InventoryAccountingService.post_adjustment_to_gl(adj)
            db.session.rollback()

    def test_adjustment_service_does_not_import_journalentry(self):
        """InventoryAdjustmentService must not reference JournalEntry directly.

        This guards the architectural boundary: GL logic belongs in
        InventoryAccountingService, not in the adjustment layer.
        """
        import ast
        import pathlib

        src = pathlib.Path(__file__).parent / 'services' / 'inventory_adjustment_service.py'
        tree = ast.parse(src.read_text())

        illegal_imports = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in getattr(node, 'names', [])]
                module = getattr(node, 'module', '') or ''
                for name in names:
                    if 'JournalEntry' in name or 'journal_entry' in name.lower():
                        illegal_imports.append(name)
                if 'JournalEntry' in module:
                    illegal_imports.append(module)

        assert illegal_imports == [], (
            f'InventoryAdjustmentService imports GL types directly: {illegal_imports}. '
            f'GL creation must go through InventoryAccountingService.'
        )

    def test_full_adjustment_flow_with_gl_stub_passes_invariant(self):
        with app.app_context():
            cat = _category(); br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 50.0)

            adj = InventoryAdjustmentService.create_manual(
                branch_id=br.id,
                lines_data=[{
                    'category_id': cat.id, 'karat': 21.0,
                    'variance_weight': -3.0,
                }],
                reason='فاقد تصنيع',
                created_by='مدير',
                auto_post=True,
            )
            db.session.flush()

            BalanceInvariantChecker.assert_clean()
            db.session.rollback()


# ── InventoryReconciliationReport ─────────────────────────────────────────────

class TestReconciliationReport:

    def test_clean_state_all_ok(self):
        with app.app_context():
            cat = _category(); br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 20.0)
            _post_invoice('بيع',  br.id, cat.id, 21.0, 5.0)

            snap = InventoryReconciliationReport.build()
            for row in snap.rows:
                if row.branch_id == br.id and row.category_id == cat.id:
                    assert row.ledger_vs_balance_ok is True
                    break
            assert snap.is_clean
            db.session.rollback()

    def test_tampered_balance_flagged(self):
        with app.app_context():
            cat = _category(); br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 10.0)

            bal = InventoryBalance.query.filter_by(
                branch_id=br.id, category_id=cat.id, karat=21.0
            ).first()
            bal.balance = 999.0
            db.session.flush()

            snap = InventoryReconciliationReport.build()
            mismatches = snap.mismatches
            assert any(
                m.branch_id == br.id and m.category_id == cat.id
                for m in mismatches
            )
            assert not snap.is_clean
            db.session.rollback()

    def test_ledger_only_bucket_flagged(self):
        """A bucket in Ledger with no Balance row must appear as a mismatch."""
        with app.app_context():
            cat = _category(); br = _branch()
            _post_invoice('شراء', br.id, cat.id, 18.0, 7.0)

            InventoryBalance.query.filter_by(
                branch_id=br.id, category_id=cat.id, karat=18.0
            ).delete()
            db.session.flush()

            snap = InventoryReconciliationReport.build()
            assert any(
                r.branch_id == br.id and r.category_id == cat.id and r.karat == 18.0
                for r in snap.mismatches
            )
            db.session.rollback()

    def test_multiple_buckets_all_correct(self):
        with app.app_context():
            cat1 = _category(); cat2 = _category(); br = _branch()
            _post_invoice('شراء', br.id, cat1.id, 18.0, 30.0)
            _post_invoice('شراء', br.id, cat2.id, 21.0, 50.0)
            _post_invoice('بيع',  br.id, cat2.id, 21.0, 10.0)

            snap = InventoryReconciliationReport.build()
            our_rows = [
                r for r in snap.rows
                if r.branch_id == br.id and r.category_id in (cat1.id, cat2.id)
            ]
            assert len(our_rows) == 2
            for r in our_rows:
                assert r.ledger_vs_balance_ok is True
            db.session.rollback()

    def test_gl_not_available_in_phase_5_stub(self):
        with app.app_context():
            snap = InventoryReconciliationReport.build()
            assert snap.gl_available is False
            for row in snap.rows:
                assert row.gl_weight is None
                assert row.ledger_vs_gl_ok is None
            db.session.rollback()

    def test_to_dict_json_serialisable(self):
        with app.app_context():
            cat = _category(); br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 5.0)

            snap = InventoryReconciliationReport.build()
            import json
            json.dumps(snap.to_dict())  # must not raise
            db.session.rollback()

    def test_ledger_sum_matches_balance_after_adjustment(self):
        """After posting an adjustment, reconciliation must still be clean."""
        with app.app_context():
            cat = _category(); br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 40.0)

            InventoryAdjustmentService.create_manual(
                branch_id=br.id,
                lines_data=[{'category_id': cat.id, 'karat': 21.0, 'variance_weight': -2.0}],
                reason='اختبار',
                created_by='test',
                auto_post=True,
            )
            db.session.flush()

            snap = InventoryReconciliationReport.build()
            our_row = next(
                (r for r in snap.rows
                 if r.branch_id == br.id and r.category_id == cat.id and r.karat == 21.0),
                None,
            )
            assert our_row is not None
            assert our_row.ledger_sum == pytest.approx(38.0)
            assert our_row.balance    == pytest.approx(38.0)
            assert our_row.ledger_vs_balance_ok is True
            db.session.rollback()


# ── Physical Count dimension in ReconciliationReport ─────────────────────────

def _run_full_count(br, cat, karat, counted_weight):
    """Helper: open → populate → count → close → approve a count session."""
    session = InventoryCountService.open_session(branch_id=br.id, opened_by='test')
    db.session.flush()
    InventoryCountService.populate_lines(session)
    db.session.flush()

    InventoryCountService.record_count(
        session, category_id=cat.id, karat=karat,
        counted_weight=counted_weight, counted_by='test',
    )
    db.session.flush()

    InventoryCountService.close_session(session)
    db.session.flush()
    session, _ = InventoryCountService.approve_session(session, approved_by='test')
    db.session.flush()
    return session


class TestReconciliationPhysicalCount:

    def test_no_count_returns_none_for_count_fields(self):
        """Bucket never counted → count fields are None, no error."""
        with app.app_context():
            cat = _category(); br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 30.0)

            snap = InventoryReconciliationReport.build()
            row = next(
                (r for r in snap.rows if r.branch_id == br.id and r.category_id == cat.id),
                None,
            )
            assert row is not None
            assert row.last_count_session_id is None
            assert row.last_count_at is None
            assert row.last_count_weight is None
            assert row.last_count_variance is None
            assert row.ledger_vs_count_ok is None
            db.session.rollback()

    def test_exact_count_shows_zero_drift(self):
        """After an exact count (counted = expected), ledger_vs_count_ok is True."""
        with app.app_context():
            cat = _category(); br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 25.0)

            _run_full_count(br, cat, 21.0, counted_weight=25.0)

            snap = InventoryReconciliationReport.build()
            row = next(
                (r for r in snap.rows if r.branch_id == br.id and r.category_id == cat.id),
                None,
            )
            assert row is not None
            assert row.last_count_weight == pytest.approx(25.0)
            assert row.ledger_vs_count_ok is True
            db.session.rollback()

    def test_count_with_variance_shows_drift(self):
        """After a count with variance, ledger_vs_count_ok reflects drift."""
        with app.app_context():
            cat = _category(); br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 50.0)

            _run_full_count(br, cat, 21.0, counted_weight=49.18)

            snap = InventoryReconciliationReport.build()
            row = next(
                (r for r in snap.rows if r.branch_id == br.id and r.category_id == cat.id),
                None,
            )
            assert row is not None
            assert row.last_count_weight == pytest.approx(49.18, abs=1e-3)
            # After adjustment posts, ledger should now match counted weight
            assert row.ledger_vs_count_ok is True
            db.session.rollback()

    def test_movements_after_count_show_drift(self):
        """New sales after an approved count create visible ledger drift."""
        with app.app_context():
            cat = _category(); br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 40.0)

            _run_full_count(br, cat, 21.0, counted_weight=40.0)

            # Sale occurs AFTER the count was approved
            _post_invoice('بيع', br.id, cat.id, 21.0, 5.0)

            snap = InventoryReconciliationReport.build()
            row = next(
                (r for r in snap.rows if r.branch_id == br.id and r.category_id == cat.id),
                None,
            )
            assert row is not None
            # Ledger is now 35g; last count was 40g
            assert row.ledger_sum == pytest.approx(35.0)
            assert row.last_count_weight == pytest.approx(40.0)
            assert row.ledger_vs_count_ok is False
            assert row in snap.count_drift_buckets
            db.session.rollback()

    def test_count_session_id_and_approved_at_populated(self):
        """last_count_session_id and last_count_at are set after approval."""
        with app.app_context():
            cat = _category(); br = _branch()
            _post_invoice('شراء', br.id, cat.id, 18.0, 15.0)

            count_session = _run_full_count(br, cat, 18.0, counted_weight=15.0)

            snap = InventoryReconciliationReport.build()
            row = next(
                (r for r in snap.rows
                 if r.branch_id == br.id and r.category_id == cat.id and r.karat == 18.0),
                None,
            )
            assert row is not None
            assert row.last_count_session_id == count_session.id
            assert row.last_count_at is not None
            db.session.rollback()

    def test_to_dict_includes_count_fields(self):
        """to_dict() must expose all count dimension fields and be JSON-safe."""
        with app.app_context():
            cat = _category(); br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 10.0)

            snap = InventoryReconciliationReport.build()
            import json
            d = snap.to_dict()
            json.dumps(d)  # must not raise

            row_d = next(
                (r for r in d['rows']
                 if r['branch_id'] == br.id and r['category_id'] == cat.id),
                None,
            )
            assert row_d is not None
            assert 'last_count_session_id' in row_d
            assert 'last_count_at' in row_d
            assert 'last_count_weight' in row_d
            assert 'last_count_variance' in row_d
            assert 'ledger_vs_count_ok' in row_d
            assert 'count_drift_buckets' in d
            db.session.rollback()
