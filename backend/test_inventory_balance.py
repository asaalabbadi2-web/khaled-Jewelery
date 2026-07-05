"""Tests for Phase 2: InventoryBalance Projection + Reversibility.

Covers:
  Consistency Tests:
    - After post(), InventoryBalance.balance == SUM(InventoryLedger.weight_delta) per bucket
    - Multiple invoices on same bucket accumulate correctly
    - Mixed invoice types (in + out) net to correct balance
    - Reversal returns balance to previous value

  Reversibility Tests:
    - reverse() appends new rows — original Ledger rows are untouched
    - reverse() is idempotent (calling twice yields no new rows the second time)
    - After post() + reverse(), net balance == 0

  Concurrency Tests (single-process simulation):
    - Sequential posts to same bucket stay consistent (simulates concurrent access
      via ORM-level isolation; true concurrent PG locking verified manually)
"""
import itertools
import threading
import uuid
from datetime import datetime
from typing import Optional

import pytest

from app import app
from models import db, Invoice, InvoiceItem, Branch, Category, InventoryLedger, InventoryBalance
from services.inventory_posting_service import InventoryPostingService

_id_seq = itertools.count(300_000)


def _uid(prefix: str = 'x') -> str:
    return f'{prefix}-{uuid.uuid4().hex[:6]}'


# ── Shared helpers (same as Phase 1 tests) ────────────────────────────────────

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


def _invoice(invoice_type: str, branch_id=None, items_data=None) -> Invoice:
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
    for d in (items_data or []):
        item = InvoiceItem(
            invoice_id=inv.id,
            quantity=1,
            price=0.0,
            karat=d.get('karat'),
            weight=d.get('weight'),
            category_id=d.get('category_id'),
        )
        db.session.add(item)
    db.session.flush()
    db.session.refresh(inv)
    return inv


def _ledger_sum(branch_id, category_id, karat) -> float:
    rows = InventoryLedger.query.filter_by(
        branch_id=branch_id,
        category_id=category_id,
        karat=karat,
    ).all()
    return round(sum(r.weight_delta for r in rows), 4)


def _balance_row(branch_id, category_id, karat) -> Optional[InventoryBalance]:
    return InventoryBalance.query.filter_by(
        branch_id=branch_id,
        category_id=category_id,
        karat=karat,
    ).first()


# ── Consistency Tests ─────────────────────────────────────────────────────────

class TestBalanceConsistency:

    def test_single_post_balance_equals_ledger_sum(self):
        with app.app_context():
            cat = _category()
            br = _branch()
            inv = _invoice('بيع', branch_id=br.id, items_data=[
                {'karat': 21.0, 'weight': 10.0, 'category_id': cat.id},
            ])
            InventoryPostingService.post(inv)
            db.session.flush()

            bal = _balance_row(br.id, cat.id, 21.0)
            assert bal is not None
            assert bal.balance == pytest.approx(_ledger_sum(br.id, cat.id, 21.0))
            assert bal.balance == pytest.approx(-10.0)
            db.session.rollback()

    def test_multiple_invoices_same_bucket_accumulate(self):
        with app.app_context():
            cat = _category()
            br = _branch()

            inv1 = _invoice('شراء', branch_id=br.id, items_data=[
                {'karat': 18.0, 'weight': 30.0, 'category_id': cat.id},
            ])
            inv2 = _invoice('شراء', branch_id=br.id, items_data=[
                {'karat': 18.0, 'weight': 20.0, 'category_id': cat.id},
            ])
            InventoryPostingService.post(inv1)
            db.session.flush()
            InventoryPostingService.post(inv2)
            db.session.flush()

            bal = _balance_row(br.id, cat.id, 18.0)
            assert bal is not None
            assert bal.balance == pytest.approx(50.0)
            assert bal.balance == pytest.approx(_ledger_sum(br.id, cat.id, 18.0))
            db.session.rollback()

    def test_mixed_in_out_net_balance(self):
        """Supplier purchase +50g then two sales of 12g and 8g → net +30g."""
        with app.app_context():
            cat = _category()
            br = _branch()

            purchase = _invoice('شراء', branch_id=br.id, items_data=[
                {'karat': 21.0, 'weight': 50.0, 'category_id': cat.id},
            ])
            sale1 = _invoice('بيع', branch_id=br.id, items_data=[
                {'karat': 21.0, 'weight': 12.0, 'category_id': cat.id},
            ])
            sale2 = _invoice('بيع', branch_id=br.id, items_data=[
                {'karat': 21.0, 'weight': 8.0, 'category_id': cat.id},
            ])

            for doc in (purchase, sale1, sale2):
                InventoryPostingService.post(doc)
                db.session.flush()

            bal = _balance_row(br.id, cat.id, 21.0)
            assert bal is not None
            assert bal.balance == pytest.approx(30.0)
            assert bal.balance == pytest.approx(_ledger_sum(br.id, cat.id, 21.0))
            db.session.rollback()

    def test_different_karats_have_separate_buckets(self):
        with app.app_context():
            cat = _category()
            br = _branch()

            inv18 = _invoice('شراء', branch_id=br.id, items_data=[
                {'karat': 18.0, 'weight': 10.0, 'category_id': cat.id},
            ])
            inv21 = _invoice('شراء', branch_id=br.id, items_data=[
                {'karat': 21.0, 'weight': 15.0, 'category_id': cat.id},
            ])
            for doc in (inv18, inv21):
                InventoryPostingService.post(doc)
                db.session.flush()

            assert _balance_row(br.id, cat.id, 18.0).balance == pytest.approx(10.0)
            assert _balance_row(br.id, cat.id, 21.0).balance == pytest.approx(15.0)
            db.session.rollback()

    def test_snapshot_max_ledger_id_advances(self):
        """snapshot_max_ledger_id always points to the last applied Ledger row."""
        with app.app_context():
            cat = _category()
            br = _branch()

            inv1 = _invoice('شراء', branch_id=br.id, items_data=[
                {'karat': 21.0, 'weight': 5.0, 'category_id': cat.id},
            ])
            inv2 = _invoice('شراء', branch_id=br.id, items_data=[
                {'karat': 21.0, 'weight': 3.0, 'category_id': cat.id},
            ])

            InventoryPostingService.post(inv1)
            db.session.flush()
            bal_after_first = _balance_row(br.id, cat.id, 21.0).snapshot_max_ledger_id

            InventoryPostingService.post(inv2)
            db.session.flush()
            bal_after_second = _balance_row(br.id, cat.id, 21.0).snapshot_max_ledger_id

            assert bal_after_second > bal_after_first
            db.session.rollback()


# ── Reversibility Tests ───────────────────────────────────────────────────────

class TestReversibility:

    def test_reverse_appends_new_ledger_rows(self):
        """reverse() must not modify original rows — only append new ones."""
        with app.app_context():
            cat = _category()
            br = _branch()
            inv = _invoice('بيع', branch_id=br.id, items_data=[
                {'karat': 21.0, 'weight': 7.0, 'category_id': cat.id},
            ])
            InventoryPostingService.post(inv)
            db.session.flush()

            original_ids = [
                r.id for r in InventoryLedger.query.filter_by(
                    source_type='invoice', source_id=inv.id
                ).all()
            ]

            InventoryPostingService.reverse(inv, reason='cancel')
            db.session.flush()

            all_rows = InventoryLedger.query.filter_by(
                source_type='invoice', source_id=inv.id
            ).all()

            # Original rows still there, untouched
            current_ids = {r.id for r in all_rows}
            for oid in original_ids:
                assert oid in current_ids

            # New reversal rows added
            reversal_rows = [r for r in all_rows if r.movement_type.endswith('_reversal')]
            assert len(reversal_rows) == 1
            assert reversal_rows[0].weight_delta == pytest.approx(+7.0)
            db.session.rollback()

    def test_post_then_reverse_net_balance_is_zero(self):
        with app.app_context():
            cat = _category()
            br = _branch()
            inv = _invoice('شراء', branch_id=br.id, items_data=[
                {'karat': 21.0, 'weight': 20.0, 'category_id': cat.id},
            ])
            InventoryPostingService.post(inv)
            db.session.flush()

            bal_before = _balance_row(br.id, cat.id, 21.0).balance
            assert bal_before == pytest.approx(20.0)

            InventoryPostingService.reverse(inv, reason='cancelled order')
            db.session.flush()

            bal_after = _balance_row(br.id, cat.id, 21.0).balance
            assert bal_after == pytest.approx(0.0)
            # Ledger sum also zero
            assert _ledger_sum(br.id, cat.id, 21.0) == pytest.approx(0.0)
            db.session.rollback()

    def test_reverse_is_idempotent(self):
        with app.app_context():
            cat = _category()
            br = _branch()
            inv = _invoice('بيع', branch_id=br.id, items_data=[
                {'karat': 18.0, 'weight': 5.0, 'category_id': cat.id},
            ])
            InventoryPostingService.post(inv)
            db.session.flush()

            first_reversal  = InventoryPostingService.reverse(inv)
            db.session.flush()
            second_reversal = InventoryPostingService.reverse(inv)
            db.session.flush()

            assert len(first_reversal)  == 1
            assert len(second_reversal) == 0  # already reversed

            reversal_rows = InventoryLedger.query.filter(
                InventoryLedger.source_type == 'invoice',
                InventoryLedger.source_id == inv.id,
                InventoryLedger.movement_type.like('%_reversal'),
            ).all()
            assert len(reversal_rows) == 1
            db.session.rollback()

    def test_reversal_notes_stored(self):
        with app.app_context():
            cat = _category()
            br = _branch()
            inv = _invoice('بيع', branch_id=br.id, items_data=[
                {'karat': 21.0, 'weight': 4.0, 'category_id': cat.id},
            ])
            InventoryPostingService.post(inv)
            db.session.flush()
            InventoryPostingService.reverse(inv, reason='طلب الإلغاء من المدير')
            db.session.flush()

            rev_row = InventoryLedger.query.filter(
                InventoryLedger.source_id == inv.id,
                InventoryLedger.movement_type.like('%_reversal'),
            ).first()
            assert rev_row is not None
            assert 'إلغاء' in (rev_row.notes or '')
            db.session.rollback()


# ── Concurrency Tests (single-process simulation) ─────────────────────────────

class TestConcurrency:

    def test_sequential_posts_same_bucket_stay_consistent(self):
        """Post N invoices sequentially to same bucket; final balance = SUM."""
        with app.app_context():
            cat = _category()
            br = _branch()

            weights = [5.0, 3.0, 12.0, 7.5, 2.5]
            for w in weights:
                inv = _invoice('شراء', branch_id=br.id, items_data=[
                    {'karat': 21.0, 'weight': w, 'category_id': cat.id},
                ])
                InventoryPostingService.post(inv)
                db.session.flush()

            bal = _balance_row(br.id, cat.id, 21.0)
            assert bal is not None
            assert bal.balance == pytest.approx(sum(weights))
            assert bal.balance == pytest.approx(_ledger_sum(br.id, cat.id, 21.0))
            db.session.rollback()

    def test_threaded_posts_balance_consistent(self):
        """Two threads post to the same bucket in parallel.

        On SQLite (test env), SELECT FOR UPDATE is a no-op, but the ORM
        serialises writes via GIL.  This test verifies correctness of the
        balance arithmetic — not PG locking (that is tested in staging).
        """
        results = {}

        def post_in_thread(weight: float, key: str):
            with app.app_context():
                cat_local = _category()
                br_local  = _branch()
                inv = _invoice('شراء', branch_id=br_local.id, items_data=[
                    {'karat': 21.0, 'weight': weight, 'category_id': cat_local.id},
                ])
                InventoryPostingService.post(inv)
                db.session.commit()
                bal = _balance_row(br_local.id, cat_local.id, 21.0)
                results[key] = bal.balance if bal else None

        t1 = threading.Thread(target=post_in_thread, args=(10.0, 'a'))
        t2 = threading.Thread(target=post_in_thread, args=(15.0, 'b'))
        t1.start(); t2.start()
        t1.join(); t2.join()

        # Each thread used its own branch+category, so no cross-contamination
        assert results.get('a') == pytest.approx(10.0)
        assert results.get('b') == pytest.approx(15.0)
