"""Utility script to seed the moving-average inventory snapshot manually.

Usage (from backend directory):
    source venv/bin/activate
    python manual_inventory_seed.py --weight 100 --avg-gold 210 --avg-manufacturing 12

If you only know the target average per gram, you can pass --avg-total directly and
leave the components empty.
"""
from __future__ import annotations

import argparse

from app import app, db  # pylint: disable=unused-import
from models import InventoryCostingConfig


def seed_inventory_snapshot(
    weight: float,
    avg_gold: float | None = None,
    avg_manufacturing: float | None = None,
    avg_total: float | None = None,
) -> InventoryCostingConfig:
    """Seed or update the single InventoryCostingConfig row with manual data."""

    if weight <= 0:
        raise ValueError("weight must be greater than zero")

    avg_gold = avg_gold or 0.0
    avg_manufacturing = avg_manufacturing or 0.0
    if avg_total is None:
        avg_total = avg_gold + avg_manufacturing

    with app.app_context():
        config = InventoryCostingConfig.query.first()
        if not config:
            config = InventoryCostingConfig()
            db.session.add(config)

        config.total_inventory_weight = weight
        config.avg_gold_price_per_gram = avg_gold
        config.avg_manufacturing_per_gram = avg_manufacturing
        config.avg_total_cost_per_gram = avg_total
        config.current_avg_cost_per_gram = avg_total
        db.session.commit()
        # Ensure the returned instance has up-to-date, non-expired attributes
        try:
            db.session.refresh(config)
        except Exception:
            # If refresh fails for any reason, proceed — the caller will see an error
            pass
        return config


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed moving-average inventory snapshot with manual values",
    )
    parser.add_argument("--weight", type=float, required=True, help="Total inventory weight in grams")
    parser.add_argument("--avg-gold", type=float, default=0.0, help="Gold cost component per gram")
    parser.add_argument(
        "--avg-manufacturing",
        type=float,
        default=0.0,
        help="Manufacturing (wage) component per gram",
    )
    parser.add_argument(
        "--avg-total",
        type=float,
        default=None,
        help="Override total average cost per gram; defaults to avg_gold + avg_manufacturing",
    )

    args = parser.parse_args()
    config = seed_inventory_snapshot(
        weight=args.weight,
        avg_gold=args.avg_gold,
        avg_manufacturing=args.avg_manufacturing,
        avg_total=args.avg_total,
    )
    print("Updated InventoryCostingConfig:")
    print(
        {
            "total_inventory_weight": config.total_inventory_weight,
            "avg_gold_price_per_gram": config.avg_gold_price_per_gram,
            "avg_manufacturing_per_gram": config.avg_manufacturing_per_gram,
            "avg_total_cost_per_gram": config.avg_total_cost_per_gram,
        }
    )


if __name__ == "__main__":
    main()
