"""Catalog router — read-only product browsing endpoints.

All gold-price logic delegates to yasargold_domain.pricing.engine;
DB access is read-only via the shared PostgreSQL instance.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Sequence

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from yasargold_commerce.db import get_db
from yasargold_commerce.infra.reservation_orm import ReservationRow
from yasargold_commerce.models import GoldPrice, Item
from yasargold_commerce.schemas import (
    CatalogListItemSchema,
    CatalogPageSchema,
    GoldRateSchema,
    PricingSnapshotSchema,
    ProductDetailSchema,
)
from yasargold_domain.pricing.quotes import QuoteStatus
from yasargold_domain.pricing.engine import PRICING_ENGINE_VERSION, karat_rate

router = APIRouter(prefix="/api/v1/catalog", tags=["catalog"])

_FRESH_TTL = timedelta(seconds=90)
_STALE_TTL = timedelta(minutes=5)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _item_slug(item_code: str) -> str:
    """Derive a URL-safe slug from item_code (e.g. 'I-000042' → 'i-000042').

    When the ERP adds a dedicated `slug` column, replace this body with:
        return item.slug
    """
    return item_code.lower()


def _gold_rate_status(fetched_at: datetime) -> QuoteStatus:
    age = datetime.now(timezone.utc) - fetched_at.replace(tzinfo=timezone.utc)
    if age <= _FRESH_TTL:
        return QuoteStatus.FRESH
    if age <= _STALE_TTL:
        return QuoteStatus.STALE
    return QuoteStatus.HALTED


def _fetch_gold_price(db: Session) -> GoldPrice | None:
    return db.execute(
        select(GoldPrice).order_by(GoldPrice.id.desc()).limit(1)
    ).scalar_one_or_none()


def _to_gold_rate_schema(row: GoldPrice) -> GoldRateSchema:
    fetched_at = row.date or datetime.now(timezone.utc)
    return GoldRateSchema(
        price_per_gram_24k=Decimal(str(row.price)),
        fetched_at=fetched_at,
        status=_gold_rate_status(fetched_at).value,
    )


def _pricing_snapshot(gp: GoldPrice | None, item_karat: str | None) -> PricingSnapshotSchema | None:
    if gp is None:
        return None
    fetched_at = (gp.date or datetime.now(timezone.utc)).replace(tzinfo=timezone.utc)
    status = _gold_rate_status(fetched_at)
    if status == QuoteStatus.HALTED:
        return None
    rate_24k = Decimal(str(gp.price))
    try:
        karat_int = int(item_karat) if item_karat else 24
    except (ValueError, TypeError):
        karat_int = 24
    now = datetime.now(timezone.utc)
    return PricingSnapshotSchema(
        gold_rate_per_gram_24k=rate_24k,
        karat_rate_per_gram=karat_rate(rate_24k, karat_int),
        issued_at=now,
        rate_timestamp=fetched_at,
        quote_valid_until=fetched_at + _FRESH_TTL,
        status=status,
        gold_price_id=gp.id,
        quote_id=None,
        pricing_engine_version=PRICING_ENGINE_VERSION,
    )


def _build_filters(karat: str | None, category_id: int | None, in_stock: bool) -> list:
    filters = []
    if karat is not None:
        filters.append(Item.karat == karat)
    if category_id is not None:
        filters.append(Item.category_id == category_id)
    if in_stock:
        filters.append(Item.stock > 0)
    return filters


def _map_list_item(row: Item) -> CatalogListItemSchema:
    net_gold = (
        (row.weight or 0.0) - (row.stones_weight or 0.0)
        if row.has_stones
        else row.weight
    )
    return CatalogListItemSchema(
        id=row.id,
        item_code=row.item_code,
        slug=_item_slug(row.item_code),
        name=row.name,
        karat=row.karat,
        weight=row.weight,
        net_gold_weight=net_gold,
        has_stones=row.has_stones,
        stock=row.stock or 0,
        category=row.category,
    )


def _map_detail_item(row: Item, gp: GoldPrice | None) -> ProductDetailSchema:
    net_gold = (
        (row.weight or 0.0) - (row.stones_weight or 0.0)
        if row.has_stones
        else row.weight
    )
    return ProductDetailSchema(
        id=row.id,
        item_code=row.item_code,
        slug=_item_slug(row.item_code),
        name=row.name,
        barcode=row.barcode,
        karat=row.karat,
        weight=row.weight,
        net_gold_weight=net_gold,
        has_stones=row.has_stones,
        stones_weight=row.stones_weight if row.has_stones else None,
        stones_value=row.stones_value if row.has_stones else None,
        count=row.count,
        wage=row.wage,
        description=row.description,
        stock=row.stock or 0,
        category=row.category,
        pricing_snapshot=_pricing_snapshot(gp, row.karat),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/products", response_model=CatalogPageSchema)
def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    karat: str | None = Query(None, description="Filter by karat, e.g. 21 or 18"),
    category_id: int | None = Query(None),
    in_stock: bool = Query(True, description="Only return items with stock > 0"),
    db: Session = Depends(get_db),
) -> CatalogPageSchema:
    """Return a paginated catalog page with the current gold rate."""
    filters = _build_filters(karat, category_id, in_stock)

    total: int = db.execute(
        select(func.count()).select_from(Item).where(*filters)
    ).scalar_one()

    rows: Sequence[Item] = (
        db.execute(
            select(Item)
            .options(joinedload(Item.category))
            .where(*filters)
            .order_by(Item.item_code)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .unique()
        .scalars()
        .all()
    )

    gp = _fetch_gold_price(db)
    return CatalogPageSchema(
        items=[_map_list_item(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
        gold_rate=_to_gold_rate_schema(gp) if gp else None,
    )


@router.get("/items/{item_id}/availability", tags=["inventory"])
def get_item_availability(item_id: int, db: Session = Depends(get_db)) -> dict:
    """Return the online reservation status of an item.

    Designed for POS screens (ADR-013 Condition 2): allows staff to see
    whether an item is currently reserved online before initiating a POS sale.

    This endpoint is read-only — it never writes to any domain or ERP table.

    Response:
        available:      True if no ACTIVE reservation holds this item
        reserved_until: ISO-8601 timestamp if reserved, null otherwise
        reservation_id: opaque ID for audit, null if not reserved
    """
    now = datetime.now(timezone.utc)
    row = db.execute(
        select(ReservationRow)
        .where(
            ReservationRow.item_id == item_id,
            ReservationRow.status == "ACTIVE",
            ReservationRow.valid_until > now,
        )
        .limit(1)
    ).scalar_one_or_none()

    if row is None:
        return {"available": True, "reserved_until": None, "reservation_id": None}

    return {
        "available": False,
        "reserved_until": row.valid_until.isoformat(),
        "reservation_id": row.id,
    }


@router.get("/products/{slug}", response_model=ProductDetailSchema)
def get_product(slug: str, db: Session = Depends(get_db)) -> ProductDetailSchema:
    """Return the full product detail page, including a live pricing snapshot.

    Pricing snapshot is None when the gold rate is HALTED (> 5 min stale or
    unreachable). The frontend should show "price unavailable" in that state.
    """
    item_code = slug.upper()
    row = (
        db.execute(
            select(Item)
            .options(joinedload(Item.category))
            .where(Item.item_code == item_code)
        )
        .unique()
        .scalar_one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"Product '{slug}' not found")

    gp = _fetch_gold_price(db)
    return _map_detail_item(row, gp)
