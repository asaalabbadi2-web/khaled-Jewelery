"""Internal machine-to-machine endpoints — ERP → Commerce.

These routes are NOT customer-facing and never appear in the public OpenAPI
spec. They form the ERP→Commerce seam: the ERP pushes events here after
completing its own write (gold price update, future: stock adjustment).

Auth: X-Internal-Secret header matched against ERP_INTERNAL_SECRET env var
      (require_internal_auth dependency — constant-time comparison).

Rate class: ops (unlimited) — callers are trusted internal services on the
            private network; volume is bounded by ERP scheduler frequency.

Registered in security.py ROUTE_SECURITY before any endpoint is callable
(Law 1: deny-by-default; Law 3: every route has a rate class).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from yasargold_commerce.auth import require_internal_auth
from yasargold_commerce.db import get_db
from yasargold_commerce.metrics import GOLD_PRICE_LAST_PUSH_TIMESTAMP, GOLD_PRICE_PUSH_TOTAL
from yasargold_commerce.models import GoldPrice

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/internal", tags=["internal"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class GoldPricePushRequest(BaseModel):
    price: float

    @field_validator("price")
    @classmethod
    def price_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("price must be positive")
        return v


class GoldPricePushResponse(BaseModel):
    price: float
    date: str     # ISO-8601 UTC


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post(
    "/gold-price",
    status_code=201,
    response_model=GoldPricePushResponse,
    summary="ERP pushes a fresh gold price to Commerce",
)
def push_gold_price(
    body: GoldPricePushRequest,
    db:   Session = Depends(get_db),
    _:    None    = Depends(require_internal_auth),
    x_correlation_id: str | None = Header(None, alias="X-Correlation-ID"),
) -> GoldPricePushResponse:
    """Insert a fresh gold price row so reservation quotes stay FRESH.

    Called by the ERP's gold-price scheduler immediately after it saves a
    new price in its own DB. This keeps the Commerce gold_price table current
    without any polling; the ERP is the single authoritative source.

    Inserting a new row (rather than updating id=1) preserves price history
    for audit and is consistent with how the ERP's own table is managed.
    The reservation router reads the latest row by id DESC.

    Returns 201 with the stored price and UTC timestamp.
    """
    now = datetime.now(timezone.utc)
    row = GoldPrice(
        price=Decimal(str(body.price)),
        date=now.replace(tzinfo=None),   # store naive UTC; contract: always UTC
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    GOLD_PRICE_PUSH_TOTAL.inc()
    GOLD_PRICE_LAST_PUSH_TIMESTAMP.set(now.timestamp())

    log.info(
        "internal.push_gold_price: stored price=%.2f id=%s correlation_id=%s",
        body.price, row.id, x_correlation_id or "none",
    )
    return GoldPricePushResponse(
        price=float(row.price),
        date=now.isoformat(),
    )
