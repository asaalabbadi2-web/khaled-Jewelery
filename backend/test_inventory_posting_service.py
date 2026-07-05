"""Tests for InventoryPostingService — Phase 1.

Covers:
  - Each of the 5 invoice types: بيع, شراء من عميل, شراء, مرتجع بيع, مرتجع شراء
  - Correct sign of weight_delta (IN vs OUT)
  - Correct bucket (branch_id, category_id, karat)
  - Idempotency: calling post() twice yields no duplicate rows
  - Unsupported invoice type returns []
  - Items with missing karat or weight are skipped
"""
import itertools
import uuid
from datetime import datetime

import pytest

from app import app
from models import db, Invoice, InvoiceItem, Branch, Category, InventoryLedger
from services.inventory_posting_service import InventoryPostingService

_id_seq = itertools.count(200_000)


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


def _invoice(invoice_type: str, branch_id=None, items_data=None) -> Invoice:
    """Create an in-memory Invoice with InvoiceItem rows (flushed to DB)."""
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

    for item_data in (items_data or []):
        item = InvoiceItem(
            invoice_id=inv.id,
            quantity=1,
            price=0.0,
            karat=item_data.get('karat'),
            weight=item_data.get('weight'),
            category_id=item_data.get('category_id'),
        )
        db.session.add(item)

    db.session.flush()
    # Reload items relationship
    db.session.refresh(inv)
    return inv


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def branch():
    with app.app_context():
        b = _branch()
        db.session.commit()
        yield b


@pytest.fixture
def category():
    with app.app_context():
        c = _category()
        db.session.commit()
        yield c


# ── helpers ───────────────────────────────────────────────────────────────────

def _sum_delta(inv_id: int) -> float:
    rows = InventoryLedger.query.filter_by(source_type='invoice', source_id=inv_id).all()
    return sum(r.weight_delta for r in rows)


def _rows(inv_id: int) -> list:
    return InventoryLedger.query.filter_by(source_type='invoice', source_id=inv_id).all()


# ── Sale (بيع) ────────────────────────────────────────────────────────────────

class TestSaleInvoice:
    def test_sale_creates_negative_delta(self):
        with app.app_context():
            cat = _category()
            br = _branch()
            inv = _invoice('بيع', branch_id=br.id, items_data=[
                {'karat': 21.0, 'weight': 10.0, 'category_id': cat.id},
            ])
            result = InventoryPostingService.post(inv)
            assert len(result) == 1
            assert result[0].weight_delta == pytest.approx(-10.0)
            assert result[0].movement_type == 'sale'
            assert result[0].karat == 21.0
            assert result[0].branch_id == br.id
            assert result[0].category_id == cat.id
            db.session.rollback()

    def test_sale_multi_items(self):
        with app.app_context():
            cat = _category()
            br = _branch()
            inv = _invoice('بيع', branch_id=br.id, items_data=[
                {'karat': 18.0, 'weight': 5.0,  'category_id': cat.id},
                {'karat': 21.0, 'weight': 8.0,  'category_id': cat.id},
                {'karat': 24.0, 'weight': 2.5,  'category_id': cat.id},
            ])
            result = InventoryPostingService.post(inv)
            assert len(result) == 3
            assert _sum_delta(inv.id) == pytest.approx(-15.5)
            db.session.rollback()


# ── Purchase from customer (شراء من عميل) ────────────────────────────────────

class TestScrapPurchaseInvoice:
    def test_scrap_purchase_creates_positive_delta(self):
        with app.app_context():
            cat = _category()
            br = _branch()
            inv = _invoice('شراء من عميل', branch_id=br.id, items_data=[
                {'karat': 18.0, 'weight': 12.0, 'category_id': cat.id},
            ])
            result = InventoryPostingService.post(inv)
            assert len(result) == 1
            assert result[0].weight_delta == pytest.approx(+12.0)
            assert result[0].movement_type == 'purchase_from_customer'
            db.session.rollback()


# ── Supplier purchase (شراء) ──────────────────────────────────────────────────

class TestSupplierPurchaseInvoice:
    def test_supplier_purchase_creates_positive_delta(self):
        with app.app_context():
            cat = _category()
            br = _branch()
            inv = _invoice('شراء', branch_id=br.id, items_data=[
                {'karat': 21.0, 'weight': 50.0, 'category_id': cat.id},
            ])
            result = InventoryPostingService.post(inv)
            assert len(result) == 1
            assert result[0].weight_delta == pytest.approx(+50.0)
            assert result[0].movement_type == 'supplier_purchase'
            db.session.rollback()


# ── Sale return (مرتجع بيع) ───────────────────────────────────────────────────

class TestSaleReturnInvoice:
    def test_sale_return_creates_positive_delta(self):
        with app.app_context():
            cat = _category()
            br = _branch()
            inv = _invoice('مرتجع بيع', branch_id=br.id, items_data=[
                {'karat': 21.0, 'weight': 7.0, 'category_id': cat.id},
            ])
            result = InventoryPostingService.post(inv)
            assert len(result) == 1
            assert result[0].weight_delta == pytest.approx(+7.0)
            assert result[0].movement_type == 'sale_return'
            db.session.rollback()


# ── Purchase return (مرتجع شراء) ──────────────────────────────────────────────

class TestPurchaseReturnInvoice:
    def test_purchase_return_creates_negative_delta(self):
        with app.app_context():
            cat = _category()
            br = _branch()
            inv = _invoice('مرتجع شراء', branch_id=br.id, items_data=[
                {'karat': 21.0, 'weight': 3.0, 'category_id': cat.id},
            ])
            result = InventoryPostingService.post(inv)
            assert len(result) == 1
            assert result[0].weight_delta == pytest.approx(-3.0)
            assert result[0].movement_type == 'purchase_return'
            db.session.rollback()

    def test_supplier_return_alias(self):
        """'مرتجع شراء (مورد)' maps to purchase_return as well."""
        with app.app_context():
            cat = _category()
            br = _branch()
            inv = _invoice('مرتجع شراء (مورد)', branch_id=br.id, items_data=[
                {'karat': 21.0, 'weight': 4.0, 'category_id': cat.id},
            ])
            result = InventoryPostingService.post(inv)
            assert len(result) == 1
            assert result[0].movement_type == 'purchase_return'
            assert result[0].weight_delta == pytest.approx(-4.0)
            db.session.rollback()


# ── Idempotency ───────────────────────────────────────────────────────────────

class TestIdempotency:
    def test_double_post_yields_no_duplicates(self):
        with app.app_context():
            cat = _category()
            br = _branch()
            inv = _invoice('بيع', branch_id=br.id, items_data=[
                {'karat': 21.0, 'weight': 6.0, 'category_id': cat.id},
            ])
            first  = InventoryPostingService.post(inv)
            db.session.flush()
            second = InventoryPostingService.post(inv)

            assert len(first)  == 1
            assert len(second) == 0  # already posted — no new rows
            assert len(_rows(inv.id)) == 1  # still exactly one row in DB
            db.session.rollback()

    def test_triple_post_still_one_row(self):
        with app.app_context():
            cat = _category()
            br = _branch()
            inv = _invoice('شراء', branch_id=br.id, items_data=[
                {'karat': 18.0, 'weight': 20.0, 'category_id': cat.id},
            ])
            InventoryPostingService.post(inv)
            db.session.flush()
            InventoryPostingService.post(inv)
            db.session.flush()
            InventoryPostingService.post(inv)
            db.session.flush()

            assert len(_rows(inv.id)) == 1
            db.session.rollback()


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_unsupported_invoice_type_returns_empty(self):
        with app.app_context():
            inv = _invoice('نوع غير معروف', items_data=[
                {'karat': 21.0, 'weight': 5.0},
            ])
            result = InventoryPostingService.post(inv)
            assert result == []
            db.session.rollback()

    def test_item_without_karat_is_skipped(self):
        with app.app_context():
            inv = _invoice('بيع', items_data=[
                {'karat': None, 'weight': 5.0},
                {'karat': 21.0, 'weight': 3.0},
            ])
            result = InventoryPostingService.post(inv)
            # Only the second item (has karat) should be posted
            assert len(result) == 1
            assert result[0].karat == 21.0
            db.session.rollback()

    def test_item_without_weight_is_skipped(self):
        with app.app_context():
            inv = _invoice('بيع', items_data=[
                {'karat': 21.0, 'weight': None},
                {'karat': 21.0, 'weight': 4.0},
            ])
            result = InventoryPostingService.post(inv)
            assert len(result) == 1
            assert result[0].weight_delta == pytest.approx(-4.0)
            db.session.rollback()

    def test_invoice_with_no_items_returns_empty(self):
        with app.app_context():
            inv = _invoice('بيع', items_data=[])
            result = InventoryPostingService.post(inv)
            assert result == []
            db.session.rollback()

    def test_unsupported_document_type_raises(self):
        with app.app_context():
            with pytest.raises(TypeError, match='unsupported document type'):
                InventoryPostingService.post({'not': 'an invoice'})
