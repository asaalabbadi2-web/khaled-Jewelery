"""
test_bonus_phase5_points_source.py
====================================
اختبارات Phase 5 — points_source على BonusRule.

بعد المعمارية الجديدة (محرك مشترك — points/engine.py):
  - points_source على القاعدة يحدد وضع المحرك، لا معادلة مستقلة.
  - cash_amount_per_point تُقرأ من Settings.sales_race_settings (لا من conditions).
  - points_source=None يتبع إعدادات سباق الأداء تماماً.
  - calc_data يحتوي على: points_source (engine mode), cash_amount_per_pt,
    points_per_gram, raw_points_float, employee_points.

الاختبارات:
  Route validation (2):
    1. points_source غير صالح ('silver') → 422 + code=points_source_not_applicable
    2. points_source على rule_type غير points_based → 422

  Engine mode mapping (2):
    3. _rule_engine_points_source('gold')  → 'gold_weight'
    4. _rule_engine_points_source('cash')  → 'profit_cash'
    5. _rule_engine_points_source(None)    → None (يتبع race settings)

  Calculator calc_data (3):
    6. points_source='gold' → calc_data.points_source == 'gold_weight'
    7. points_source='cash' → calc_data.points_source == 'profit_cash'
    8. points_source=None   → calc_data.points_source == race_settings value

  Snapshots (1):
    9. rule_snapshot يسجّل points_source
"""

import pytest
from datetime import date
from unittest.mock import patch, MagicMock

from app import app
from models import db, Employee, BonusRule, EmployeeBonus, Invoice
from bonus_calculator import BonusCalculator, _rule_engine_points_source


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def auth_token():
    with app.app_context():
        from auth_decorators import generate_token
        from models import User
        admin = User.query.filter_by(username='admin').first()
        assert admin
        return f'Bearer {generate_token(admin)}'


@pytest.fixture
def points_rule_gold():
    with app.app_context():
        rule = BonusRule(
            name='test_points_gold',
            rule_type='points_based',
            bonus_type='fixed',
            bonus_value=100.0,
            is_active=True,
            points_source='gold',
            conditions={'points_period': 'month', 'min_points': 0},
            created_by='test',
        )
        db.session.add(rule)
        db.session.commit()
        rule_id = rule.id
    yield rule_id
    with app.app_context():
        BonusRule.query.filter_by(id=rule_id).delete()
        db.session.commit()


@pytest.fixture
def points_rule_cash():
    with app.app_context():
        rule = BonusRule(
            name='test_points_cash',
            rule_type='points_based',
            bonus_type='fixed',
            bonus_value=200.0,
            is_active=True,
            points_source='cash',
            conditions={'points_period': 'month', 'min_points': 0},
            created_by='test',
        )
        db.session.add(rule)
        db.session.commit()
        rule_id = rule.id
    yield rule_id
    with app.app_context():
        BonusRule.query.filter_by(id=rule_id).delete()
        db.session.commit()


@pytest.fixture
def points_rule_null_source():
    with app.app_context():
        rule = BonusRule(
            name='test_points_null_source',
            rule_type='points_based',
            bonus_type='fixed',
            bonus_value=50.0,
            is_active=True,
            points_source=None,
            conditions={'points_period': 'month', 'min_points': 0},
            created_by='test',
        )
        db.session.add(rule)
        db.session.commit()
        rule_id = rule.id
    yield rule_id
    with app.app_context():
        BonusRule.query.filter_by(id=rule_id).delete()
        db.session.commit()


# ── Route Validation ──────────────────────────────────────────────────────────

class TestPointsSourceRouteValidation:

    def test_invalid_points_source_returns_422(self, auth_token):
        """points_source='silver' على قاعدة points_based → 422."""
        with app.test_client() as client:
            resp = client.post(
                '/api/bonus-rules',
                json={
                    'name': 'invalid_source_test',
                    'rule_type': 'points_based',
                    'bonus_type': 'points_per_unit',
                    'bonus_value': 10.0,
                    'points_source': 'silver',
                    'conditions': {},
                },
                headers={'Authorization': auth_token},
            )
        assert resp.status_code == 422, f"توقعنا 422 — {resp.get_json()}"
        body = resp.get_json()
        assert body.get('code') == 'points_source_not_applicable'
        assert 'silver' in body.get('message', '')

    def test_points_source_on_non_points_rule_returns_422(self, auth_token):
        """points_source='gold' على sales_target → 422."""
        with app.test_client() as client:
            resp = client.post(
                '/api/bonus-rules',
                json={
                    'name': 'wrong_type_source_test',
                    'rule_type': 'sales_target',
                    'bonus_type': 'percentage',
                    'bonus_value': 5.0,
                    'points_source': 'gold',
                },
                headers={'Authorization': auth_token},
            )
        assert resp.status_code == 422, f"توقعنا 422 — {resp.get_json()}"
        body = resp.get_json()
        assert body.get('code') == 'points_source_not_applicable'

    def test_cash_source_without_cash_amount_creates_rule(self, auth_token):
        """points_source='cash' بدون conditions.cash_amount_per_point → 201.
        cash_amount_per_point الآن يُقرأ من Settings.sales_race_settings، لا من conditions.
        """
        with app.test_client() as client:
            resp = client.post(
                '/api/bonus-rules',
                json={
                    'name': 'cash_no_cond_test',
                    'rule_type': 'points_based',
                    'bonus_type': 'fixed',
                    'bonus_value': 100.0,
                    'points_source': 'cash',
                    'conditions': {'points_period': 'month'},
                },
                headers={'Authorization': auth_token},
            )
        assert resp.status_code == 201, (
            f'cash بدون conditions.cash_amount_per_point يجب أن يُنشئ القاعدة — '
            f'{resp.get_json()}'
        )
        # Cleanup
        rule_id = resp.get_json()['rule']['id']
        with app.app_context():
            BonusRule.query.filter_by(id=rule_id).delete()
            db.session.commit()

    def test_gold_source_creates_rule_successfully(self, auth_token):
        """points_source='gold' على points_based → 201."""
        with app.test_client() as client:
            resp = client.post(
                '/api/bonus-rules',
                json={
                    'name': 'valid_gold_source_test',
                    'rule_type': 'points_based',
                    'bonus_type': 'points_per_unit',
                    'bonus_value': 10.0,
                    'points_source': 'gold',
                    'conditions': {'points_period': 'month'},
                },
                headers={'Authorization': auth_token},
            )
        assert resp.status_code == 201, f"توقعنا 201 — {resp.get_json()}"
        body = resp.get_json()
        assert body['rule']['points_source'] == 'gold'
        # Cleanup
        with app.app_context():
            BonusRule.query.filter_by(id=body['rule']['id']).delete()
            db.session.commit()


# ── Engine Mode Mapping ────────────────────────────────────────────────────────

class TestEngineModeMappingUnit:
    """_rule_engine_points_source يُعيّن BonusRule.points_source → وضع المحرك."""

    def test_gold_maps_to_gold_weight(self):
        """'gold' → 'gold_weight' (profit_gold × points_per_gram لكل الأنواع)."""
        class _Rule:
            points_source = 'gold'
        assert _rule_engine_points_source(_Rule()) == 'gold_weight'

    def test_cash_maps_to_profit_cash(self):
        """'cash' → 'profit_cash' (profit_cash ÷ cpp للبيع، profit_gold × ppg للشراء)."""
        class _Rule:
            points_source = 'cash'
        assert _rule_engine_points_source(_Rule()) == 'profit_cash'

    def test_null_returns_none(self):
        """None → None (يتبع race settings — BonusCalculator يُحدّد الوضع من Settings)."""
        class _Rule:
            points_source = None
        assert _rule_engine_points_source(_Rule()) is None

    def test_unknown_returns_none(self):
        """قيمة غير معروفة → None (الافتراضي من race settings)."""
        class _Rule:
            points_source = 'silver'
        assert _rule_engine_points_source(_Rule()) is None


# ── Calculator calc_data Structure ────────────────────────────────────────────

class TestPointsSourceCalculatorData:
    """يتحقق أن calc_data يعكس وضع المحرك الصحيح ومعاملاته."""

    def _calc_data(self, rule_id, race_cfg=None):
        """يُشغّل calculate_points_bonus ويُعيد calc_data، أو None."""
        if race_cfg is None:
            race_cfg = {
                'points_source':         'profit_cash',
                'cash_amount_per_point': 50.0,
                'points_per_gram':       10.0,
                'point_rules':           None,
            }
        with app.app_context():
            emp  = Employee.query.filter_by(is_active=True).first()
            rule = BonusRule.query.get(rule_id)
            with patch('bonus_calculator.get_race_points_config', return_value=race_cfg):
                result = BonusCalculator.calculate_points_bonus(
                    emp, rule,
                    date(2026, 6, 1), date(2026, 6, 30),
                )
        return result

    def test_gold_source_engine_mode_in_calc_data(self, points_rule_gold):
        """points_source='gold' → calc_data['points_source'] == 'gold_weight'."""
        result = self._calc_data(points_rule_gold)
        assert result is not None, 'fixed bonus يجب أن ينتج نتيجة'
        _raw, _amt, calc_data, _min, _max = result
        assert calc_data['points_source'] == 'gold_weight'
        assert 'points_per_gram' in calc_data
        assert 'raw_points_float' in calc_data

    def test_cash_source_engine_mode_in_calc_data(self, points_rule_cash):
        """points_source='cash' → calc_data['points_source'] == 'profit_cash'."""
        result = self._calc_data(points_rule_cash)
        assert result is not None
        _raw, _amt, calc_data, _min, _max = result
        assert calc_data['points_source'] == 'profit_cash'
        assert 'cash_amount_per_pt' in calc_data
        assert 'points_per_gram' in calc_data

    def test_null_source_follows_race_settings(self, points_rule_null_source):
        """points_source=None → calc_data['points_source'] == race_settings.points_source."""
        for race_src in ('profit_cash', 'gold_weight'):
            result = self._calc_data(
                points_rule_null_source,
                race_cfg={
                    'points_source':         race_src,
                    'cash_amount_per_point': 50.0,
                    'points_per_gram':       10.0,
                    'point_rules':           None,
                },
            )
            assert result is not None
            _raw, _amt, calc_data, _min, _max = result
            assert calc_data['points_source'] == race_src, (
                f'points_source=None يجب أن يُنتج {race_src} عند race_settings.points_source={race_src}'
            )

    def test_calc_data_always_has_core_keys(self, points_rule_cash):
        """calc_data يحتوي دائماً على المفاتيح الأساسية بغض النظر عن الوضع."""
        result = self._calc_data(points_rule_cash)
        assert result is not None
        _raw, _amt, calc_data, _min, _max = result
        for key in ('points_source', 'cash_amount_per_pt', 'points_per_gram',
                    'raw_points_float', 'employee_points', 'invoice_count'):
            assert key in calc_data, f'مفتاح "{key}" مفقود من calc_data'


# ── Snapshots ─────────────────────────────────────────────────────────────────

class TestPointsSourceSnapshots:

    def test_rule_snapshot_records_points_source(self, points_rule_cash):
        """to_snapshot() يُصدّر points_source بقيمته الصحيحة."""
        with app.app_context():
            rule = BonusRule.query.get(points_rule_cash)
            snap = rule.to_snapshot()
        assert 'points_source' in snap, 'to_snapshot() يجب أن يُصدّر points_source'
        assert snap['points_source'] == 'cash'

    def test_calculation_snapshot_inputs_record_engine_mode(self, points_rule_cash):
        """bonus.calculation_snapshot.inputs.points_source يعكس وضع المحرك."""
        race_cfg = {
            'points_source':         'profit_cash',
            'cash_amount_per_point': 50.0,
            'points_per_gram':       10.0,
            'point_rules':           None,
        }
        with app.app_context():
            emp  = Employee.query.filter_by(is_active=True).first()
            rule = BonusRule.query.get(points_rule_cash)
            with patch('bonus_calculator.get_race_points_config', return_value=race_cfg):
                bonus = BonusCalculator.calculate_bonus(
                    emp, rule,
                    date(2026, 7, 1), date(2026, 7, 31),
                )
        assert bonus is not None
        snap = bonus.calculation_snapshot
        assert snap is not None
        assert snap['inputs']['points_source'] == 'profit_cash'
        assert 'cash_amount_per_pt' in snap['inputs']
