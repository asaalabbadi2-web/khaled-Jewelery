"""Contract tests for GET /api/v1/catalog/products and /products/{slug}.

These tests assert the *shape* of the API response — not business logic.
They run without a real database: a fake session is injected via
FastAPI dependency_overrides so they are safe in CI with no PostgreSQL.

List endpoint contract (CatalogListItemSchema):
  - id, item_code, slug, name, stock are always present
  - slug is URL-safe (lowercase, alphanumeric + hyphens, no spaces)
  - karat, when present, is one of the recognised gold karats
  - weight and net_gold_weight are positive when present
  - net_gold_weight ≤ weight
  - gold_rate.status is one of FRESH | STALE | HALTED

Detail endpoint contract (ProductDetailSchema):
  - Superset of list fields plus: barcode, stones_*, count, wage, description
  - pricing_snapshot present and FRESH when gold rate is fresh
  - pricing_snapshot is None when gold rate is HALTED
  - pricing_snapshot.karat_rate_per_gram ≤ pricing_snapshot.gold_rate_per_gram_24k
  - 404 returned for unknown slugs
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from yasargold_commerce.db import get_db
from yasargold_commerce.main import app
from yasargold_commerce.models import Category, GoldPrice, Item
from yasargold_commerce.schemas import QuoteStatus

_VALID_KARATS = {"18", "21", "22", "24"}
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*$")
_VALID_STATUSES = {s.value for s in QuoteStatus}
_RESERVATION_ALLOWED = {QuoteStatus.FRESH.value, QuoteStatus.LOCKED.value}


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def _make_item(
    id: int = 1,
    item_code: str = "I-000001",
    name: str = "خاتم ذهب",
    karat: str = "21",
    weight: float = 8.5,
    stock: int = 3,
    has_stones: bool = False,
    category: Category | None = None,
) -> Item:
    item = Item(
        id=id,
        item_code=item_code,
        name=name,
        barcode=None,
        category_id=category.id if category else None,
        karat=karat,
        weight=weight,
        has_stones=has_stones,
        stones_weight=0.3 if has_stones else 0.0,
        stones_value=120.0 if has_stones else 0.0,
        count=1,
        wage=15.0,
        description="وصف الصنف",
        price=1200.0,
        stock=stock,
    )
    item.category = category
    return item


def _make_gold_price(price: float = 230.0, age_seconds: float = 30.0) -> GoldPrice:
    return GoldPrice(
        id=1,
        price=price,
        date=datetime.now(timezone.utc) - timedelta(seconds=age_seconds),
    )


def _fake_db(items: list[Item], gp: GoldPrice | None = None, single_item: Item | None = None):
    """Return a FastAPI dependency override that mocks the DB session."""
    resolved_gp = gp if gp is not None else _make_gold_price()

    def _session():
        mock = MagicMock()

        def execute(stmt):
            result = MagicMock()
            result.scalar_one.return_value = len(items)
            result.scalar_one_or_none.return_value = resolved_gp

            unique_result = MagicMock()
            unique_result.scalars.return_value.all.return_value = items
            # for single-item detail lookup
            target = single_item if single_item is not None else (items[0] if items else None)
            unique_result.scalar_one_or_none.return_value = target
            result.unique.return_value = unique_result
            return result

        mock.execute.side_effect = execute
        yield mock

    return _session


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client_with_items():
    cat = Category(id=1, name="خواتم", karat="21")
    items = [
        _make_item(id=1, item_code="I-000001", karat="21", weight=8.5, category=cat),
        _make_item(id=2, item_code="I-000002", karat="18", weight=5.0, has_stones=True),
    ]
    app.dependency_overrides[get_db] = _fake_db(items)
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client_empty():
    app.dependency_overrides[get_db] = _fake_db([])
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client_halted_rate():
    """Gold rate older than 5 minutes → HALTED."""
    items = [_make_item()]
    stale_gp = _make_gold_price(age_seconds=400.0)
    app.dependency_overrides[get_db] = _fake_db(items, gp=stale_gp)
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client_single_item():
    item = _make_item(id=1, item_code="I-000001", karat="21", weight=8.5)
    app.dependency_overrides[get_db] = _fake_db([item], single_item=item)
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client_missing_item():
    app.dependency_overrides[get_db] = _fake_db([], single_item=None)
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Contract: GET /api/v1/catalog/products  (list)
# ---------------------------------------------------------------------------

class TestListProductsContract:
    def test_200_shape(self, client_with_items):
        r = client_with_items.get("/api/v1/catalog/products")
        assert r.status_code == 200
        body = r.json()
        assert "items" in body
        assert "total" in body
        assert "page" in body
        assert "page_size" in body

    def test_total_is_non_negative_int(self, client_with_items):
        body = client_with_items.get("/api/v1/catalog/products").json()
        assert isinstance(body["total"], int) and body["total"] >= 0

    def test_empty_catalog_returns_zero_total(self, client_empty):
        body = client_empty.get("/api/v1/catalog/products").json()
        assert body["total"] == 0
        assert body["items"] == []

    def test_list_item_required_fields(self, client_with_items):
        body = client_with_items.get("/api/v1/catalog/products").json()
        for item in body["items"]:
            assert "id" in item
            assert "item_code" in item
            assert "slug" in item
            assert "name" in item
            assert "stock" in item

    def test_list_item_no_pricing_snapshot(self, client_with_items):
        """List items are lean — no pricing_snapshot field."""
        body = client_with_items.get("/api/v1/catalog/products").json()
        for item in body["items"]:
            assert "pricing_snapshot" not in item

    def test_slug_is_url_safe(self, client_with_items):
        body = client_with_items.get("/api/v1/catalog/products").json()
        for item in body["items"]:
            assert _SLUG_RE.match(item["slug"]), f"Bad slug: {item['slug']!r}"
            assert " " not in item["slug"]

    def test_stock_non_negative(self, client_with_items):
        body = client_with_items.get("/api/v1/catalog/products").json()
        for item in body["items"]:
            assert item["stock"] >= 0

    def test_karat_valid_when_present(self, client_with_items):
        body = client_with_items.get("/api/v1/catalog/products").json()
        for item in body["items"]:
            if item["karat"] is not None:
                assert item["karat"] in _VALID_KARATS

    def test_weight_positive_when_present(self, client_with_items):
        body = client_with_items.get("/api/v1/catalog/products").json()
        for item in body["items"]:
            if item["weight"] is not None:
                assert item["weight"] > 0

    def test_net_gold_weight_lte_weight(self, client_with_items):
        body = client_with_items.get("/api/v1/catalog/products").json()
        for item in body["items"]:
            if item["net_gold_weight"] is not None and item["weight"] is not None:
                assert item["net_gold_weight"] <= item["weight"]

    def test_gold_rate_status_valid(self, client_with_items):
        body = client_with_items.get("/api/v1/catalog/products").json()
        if body["gold_rate"] is not None:
            assert body["gold_rate"]["status"] in _VALID_STATUSES

    def test_gold_rate_price_positive(self, client_with_items):
        body = client_with_items.get("/api/v1/catalog/products").json()
        if body["gold_rate"] is not None:
            assert float(body["gold_rate"]["price_per_gram_24k"]) > 0

    def test_pagination_defaults(self, client_with_items):
        body = client_with_items.get("/api/v1/catalog/products").json()
        assert body["page"] == 1
        assert body["page_size"] == 20


# ---------------------------------------------------------------------------
# Contract: GET /api/v1/catalog/products/{slug}  (detail)
# ---------------------------------------------------------------------------

class TestGetProductBySlugContract:
    def test_200_for_known_slug(self, client_single_item):
        r = client_single_item.get("/api/v1/catalog/products/i-000001")
        assert r.status_code == 200
        body = r.json()
        assert body["item_code"] == "I-000001"
        assert body["slug"] == "i-000001"

    def test_404_for_unknown_slug(self, client_missing_item):
        r = client_missing_item.get("/api/v1/catalog/products/i-999999")
        assert r.status_code == 404

    def test_detail_has_extended_fields(self, client_single_item):
        body = client_single_item.get("/api/v1/catalog/products/i-000001").json()
        for field in ("id", "item_code", "slug", "name", "stock", "description", "wage", "count"):
            assert field in body, f"Missing field: {field}"

    def test_slug_round_trip(self, client_single_item):
        body = client_single_item.get("/api/v1/catalog/products/i-000001").json()
        assert body["slug"] == "i-000001"

    def test_pricing_snapshot_present_when_fresh(self, client_single_item):
        body = client_single_item.get("/api/v1/catalog/products/i-000001").json()
        snap = body.get("pricing_snapshot")
        assert snap is not None, "pricing_snapshot must be present for a FRESH gold rate"
        assert snap["status"] == "FRESH"

    def test_pricing_snapshot_none_when_halted(self, client_halted_rate):
        body = client_halted_rate.get("/api/v1/catalog/products/i-000001").json()
        assert body.get("pricing_snapshot") is None, (
            "pricing_snapshot must be None when gold rate is HALTED"
        )

    def test_pricing_snapshot_fields(self, client_single_item):
        snap = client_single_item.get("/api/v1/catalog/products/i-000001").json()["pricing_snapshot"]
        for field in ("gold_rate_per_gram_24k", "karat_rate_per_gram",
                      "issued_at", "rate_timestamp", "quote_valid_until", "status",
                      "gold_price_id", "quote_id", "pricing_engine_version"):
            assert field in snap, f"Missing field in pricing_snapshot: {field}"

    def test_issued_at_lte_quote_valid_until(self, client_single_item):
        snap = client_single_item.get("/api/v1/catalog/products/i-000001").json()["pricing_snapshot"]
        assert snap["issued_at"] <= snap["quote_valid_until"]

    def test_gold_price_id_is_positive_int(self, client_single_item):
        snap = client_single_item.get("/api/v1/catalog/products/i-000001").json()["pricing_snapshot"]
        assert isinstance(snap["gold_price_id"], int)
        assert snap["gold_price_id"] > 0

    def test_pricing_snapshot_status_is_known_enum(self, client_single_item):
        snap = client_single_item.get("/api/v1/catalog/products/i-000001").json()["pricing_snapshot"]
        assert snap["status"] in _VALID_STATUSES, f"Unknown status: {snap['status']!r}"

    def test_fresh_status_allows_reservation(self, client_single_item):
        snap = client_single_item.get("/api/v1/catalog/products/i-000001").json()["pricing_snapshot"]
        assert snap["status"] in _RESERVATION_ALLOWED

    def test_pricing_engine_version_present(self, client_single_item):
        snap = client_single_item.get("/api/v1/catalog/products/i-000001").json()["pricing_snapshot"]
        assert snap["pricing_engine_version"] == "v1"

    def test_karat_rate_lte_24k_rate(self, client_single_item):
        snap = client_single_item.get("/api/v1/catalog/products/i-000001").json()["pricing_snapshot"]
        assert float(snap["karat_rate_per_gram"]) <= float(snap["gold_rate_per_gram_24k"])

    def test_quote_valid_until_after_rate_timestamp(self, client_single_item):
        snap = client_single_item.get("/api/v1/catalog/products/i-000001").json()["pricing_snapshot"]
        assert snap["quote_valid_until"] > snap["rate_timestamp"]
