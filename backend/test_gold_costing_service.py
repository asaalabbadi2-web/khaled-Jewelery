#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبار خدمات متوسط تكلفة الذهب (Moving Average)."""

from datetime import datetime
from math import isclose

from app import app
from models import db, InventoryCostingConfig
from gold_costing_service import (
    GoldCostingService,
    calculate_profit_weight,
    calculate_closing_difference,
)


def _restore_configs(backup_rows):
    """إرجاع جدول الإعدادات إلى حالته الأصلية بعد الاختبار."""
    InventoryCostingConfig.query.delete()
    db.session.flush()

    for row in backup_rows:
        restored = InventoryCostingConfig(
            id=row['id'],
            costing_method=row['costing_method'],
            current_avg_cost_per_gram=row['current_avg_cost_per_gram'],
            avg_gold_price_per_gram=row['avg_gold_price_per_gram'],
            avg_manufacturing_per_gram=row['avg_manufacturing_per_gram'],
            avg_total_cost_per_gram=row['avg_total_cost_per_gram'],
            total_inventory_weight=row['total_inventory_weight'],
            total_gold_value=row['total_gold_value'],
            total_manufacturing_value=row['total_manufacturing_value'],
            last_purchase_price=row['last_purchase_price'],
            last_purchase_weight=row['last_purchase_weight'],
        )
        if row['last_updated']:
            restored.last_updated = datetime.fromisoformat(row['last_updated'])
        if row['created_at']:
            restored.created_at = datetime.fromisoformat(row['created_at'])
        db.session.add(restored)

    db.session.commit()


def _run_assertions():
    # إنشاء إعدادات جديدة نظيفة
    InventoryCostingConfig.query.delete()
    db.session.commit()

    snapshot = GoldCostingService.snapshot()
    assert snapshot.avg_total == 0
    assert snapshot.avg_gold == 0
    assert snapshot.avg_manufacturing == 0

    GoldCostingService.update_average_on_purchase(
        weight_grams=10,
        gold_price_per_gram=250,
        manufacturing_wage_per_gram=15,
    )

    config = InventoryCostingConfig.query.first()
    assert config is not None
    assert isclose(config.total_inventory_weight, 10, rel_tol=1e-6)
    assert isclose(config.total_gold_value, 2500, rel_tol=1e-6)
    assert isclose(config.total_manufacturing_value, 150, rel_tol=1e-6)
    assert isclose(config.avg_gold_price_per_gram, 250, rel_tol=1e-6)
    assert isclose(config.avg_manufacturing_per_gram, 15, rel_tol=1e-6)

    GoldCostingService.consume_inventory(weight_grams=4)
    config = InventoryCostingConfig.query.first()
    assert isclose(config.total_inventory_weight, 6, rel_tol=1e-6)
    assert isclose(config.total_gold_value, 1500, rel_tol=1e-6)
    assert isclose(config.total_manufacturing_value, 90, rel_tol=1e-6)

    cogs = GoldCostingService.calculate_cogs(2)
    assert isclose(cogs['total_cogs'], 530, rel_tol=1e-6)
    assert isclose(cogs['gold_component'], 500, rel_tol=1e-6)
    assert isclose(cogs['manufacturing_component'], 30, rel_tol=1e-6)

    profit_weight = calculate_profit_weight(200.0, reference_price_per_gram=250.0)
    assert isclose(profit_weight, 0.8, rel_tol=1e-6)

    closing_diff = calculate_closing_difference(profit_weight, 200.0, close_price=300.0)
    assert isclose(closing_diff['close_value'], 240.0, rel_tol=1e-6)
    assert isclose(closing_diff['difference_value'], 40.0, rel_tol=1e-6)
    # difference_weight = profit_weight - (profit_cash / close_price)
    assert isclose(closing_diff['difference_weight'], 0.1333333333, rel_tol=1e-6)

    # Defensive: zero snapshot or close price should not blow up
    assert calculate_profit_weight(150, reference_price_per_gram=0) == 0.0
    zero_diff = calculate_closing_difference(1.5, 0, close_price=0)
    assert zero_diff['close_value'] == 0.0
    assert zero_diff['difference_weight'] == 0.0


if __name__ == '__main__':
    with app.app_context():
        backup_rows = [row.to_dict() for row in InventoryCostingConfig.query.all()]
        try:
            _run_assertions()
            print('✅ GoldCostingService tests passed successfully.')
        except AssertionError as exc:
            print('❌ GoldCostingService test failed:', exc)
            raise
        finally:
            _restore_configs(backup_rows)
            print('ℹ️ InventoryCostingConfig table restored to previous state.')
