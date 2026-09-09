"""Gold price provider — single source of truth for current spot price.

Extracted from routes.py to break the circular dependency:
  dual_system_helpers → routes.get_current_gold_price
"""
from __future__ import annotations

from .constants import SAR_USD_PEG, TROY_OZ_TO_GRAMS


def get_main_karat() -> int:
    from models import Settings
    settings = Settings.query.first()
    return settings.main_karat if settings else 21


def get_current_gold_price() -> dict:
    """Return latest gold price snapshot as SAR per gram.

    Returns:
        dict with price_per_gram_24k, price_per_gram_main_karat,
        main_karat, source, updated_at
    """
    from models import GoldPrice

    price_per_gram_24k = 0.0
    source = "database"
    updated_at = None

    latest = GoldPrice.query.order_by(GoldPrice.date.desc()).first()
    if latest and latest.price:
        try:
            price_per_gram_24k = (latest.price / TROY_OZ_TO_GRAMS) * SAR_USD_PEG
            updated_at = latest.date.isoformat() if latest.date else None
        except Exception as exc:
            print(f"⚠️ Failed to normalize gold price: {exc}")
            price_per_gram_24k = 0.0

    if price_per_gram_24k <= 0:
        source = "fallback"
        price_per_gram_24k = 400.0

    main_karat = get_main_karat()
    price_per_gram_main_karat = (price_per_gram_24k * main_karat) / 24.0

    return {
        "price_per_gram_24k": round(price_per_gram_24k, 4),
        "price_per_gram_main_karat": round(price_per_gram_main_karat, 4),
        "main_karat": main_karat,
        "source": source,
        "updated_at": updated_at,
    }
