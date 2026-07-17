"""Gold pricing engine — pure domain logic, no DB, no framework imports.

All values passed in; callers provide the gold rate and system karat.
CI-enforced: no flask / fastapi / redis / sqlalchemy import allowed here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

# Bump this whenever the pricing formula or rounding rules change.
# Embedded in every PricingSnapshot so old quotes can be audited correctly.
PRICING_ENGINE_VERSION = "v1"


@dataclass(frozen=True)
class GoldRate:
    karat: int
    price_per_gram: Decimal
    source: str
    fetched_at: datetime
    status: str  # FRESH | STALE | HALTED


@dataclass(frozen=True)
class PricingInput:
    weight_grams: Decimal
    karat: int
    making_charge: Decimal = Decimal("0")
    stone_price: Decimal = Decimal("0")
    discount: Decimal = Decimal("0")
    tax_rate: Decimal = Decimal("0")
    pricing_rule_version: str = "v1"


@dataclass(frozen=True)
class PriceQuote:
    weight_grams: Decimal
    karat: int
    gold_rate_per_gram: Decimal
    gold_component: Decimal
    making_charge: Decimal
    stone_price: Decimal
    discount: Decimal
    subtotal: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    total: Decimal
    currency: str
    quoted_at: datetime
    pricing_rule_version: str
    gold_rate_source: str
    gold_rate_fetched_at: datetime


def _d(value: object) -> Decimal:
    """Safely coerce to Decimal."""
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _round(value: Decimal, places: int = 2) -> Decimal:
    quantize_str = Decimal("0." + "0" * places)
    return value.quantize(quantize_str, rounding=ROUND_HALF_UP)


def compute_price(rate: GoldRate, inp: PricingInput, currency: str = "SAR") -> PriceQuote:
    """Compute a full PriceQuote from a GoldRate and PricingInput.

    Formula:
        gold_component = weight_grams × price_per_gram
        subtotal       = gold_component + making_charge + stone_price − discount
        tax_amount     = subtotal × tax_rate
        total          = subtotal + tax_amount
    """
    gold_component = _round(_d(inp.weight_grams) * _d(rate.price_per_gram))
    subtotal = _round(
        gold_component
        + _d(inp.making_charge)
        + _d(inp.stone_price)
        - _d(inp.discount)
    )
    tax_amount = _round(subtotal * _d(inp.tax_rate))
    total = _round(subtotal + tax_amount)

    return PriceQuote(
        weight_grams=_d(inp.weight_grams),
        karat=inp.karat,
        gold_rate_per_gram=_d(rate.price_per_gram),
        gold_component=gold_component,
        making_charge=_d(inp.making_charge),
        stone_price=_d(inp.stone_price),
        discount=_d(inp.discount),
        subtotal=subtotal,
        tax_rate=_d(inp.tax_rate),
        tax_amount=tax_amount,
        total=total,
        currency=currency,
        quoted_at=datetime.now(timezone.utc),
        pricing_rule_version=inp.pricing_rule_version,
        gold_rate_source=rate.source,
        gold_rate_fetched_at=rate.fetched_at,
    )


def convert_between_karats(weight: Decimal, from_karat: int, to_karat: int) -> Decimal:
    """Convert *weight* at *from_karat* to equivalent weight at *to_karat*."""
    if from_karat == 0 or to_karat == 0:
        return Decimal("0")
    return _round(weight * _d(from_karat) / _d(to_karat), 4)


def karat_rate(rate_24k: Decimal, karat: int) -> Decimal:
    """Derive per-gram rate for *karat* from the 24k spot price."""
    return _round(rate_24k * _d(karat) / Decimal("24"))
