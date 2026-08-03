"""
test_bonus_phase5_points_source.py
====================================
اختبارات Phase 5 — points_source على BonusRule.

الاختبارات:
  Route validation (3):
    1. points_source غير صالح ('silver') → 422 + code=points_source_not_applicable
    2. points_source على rule_type غير points_based → 422
    3. points_source='cash' بدون conditions.cash_amount_per_point → 422

  Calculator (3):
    4. points_source='gold' → يستخدم profit_gold × points_per_gram
    5. points_source=None   → نفس سلوك gold (التوافق الخلفي)
    6. points_source='cash' → يستخدم profit_cash ÷ cash_amount_per_point

  Snapshots (2):
    7. rule_snapshot يسجّل points_source
    8. calculation_snapshot.inputs يسجّل points_source
"""

import pytest
from datetime import date, datetime
from unittest.mock import patch

from app import app
from models import db, Employee, BonusRule, EmployeeBonus, Invoice
from bonus_calculator import BonusCalculator, _resolve_points_source


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
def points_rule_gold(scope='function'):
    """BonusRule من نوع points_based + points_source='gold'."""
    with app.app_context():
        rule = BonusRule(
            name='test_points_gold',
            rule_type='points_based',
            bonus_type='points_per_unit',
            bonus_value=10.0,
            is_active=True,
            points_source='gold',
            conditions={'points_period': 'month'},
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
    """BonusRule من نوع points_based + points_source='cash'."""
    with app.app_context():
        rule = BonusRule(
            name='test_points_cash',
            rule_type='points_based',
            bonus_type='points_per_unit',
            bonus_value=5.0,
            is_active=True,
            points_source='cash',
            conditions={'cash_amount_per_point': 100.0, 'points_period': 'month'},
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
    """BonusRule من نوع points_based + points_source=None (الافتراضي)."""
    with app.app_context():
        rule = BonusRule(
            name='test_points_null_source',
            rule_type='points_based',
            bonus_type='points_per_unit',
            bonus_value=8.0,
            is_active=True,
            points_source=None,
            conditions={'points_period': 'month'},
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
                    'conditions': {'cash_amount_per_point': 100.0},
                },
                headers={'Authorization': auth_token},
            )
        assert resp.status_code == 422, f"توقعنا 422 — {resp.get_json()}"
        body = resp.get_json()
        assert body.get('code') == 'points_source_not_applicable'
        assert 'silver' in body.get('message', '')

    def test_points_source_on_non_points_rule_returns_422(self, auth_token):
        """points_source='gold' على sales_target → 422 (لا ينطبق إلا على points_based)."""
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
        assert 'points_based' in body.get('message', '')

    def test_cash_source_without_cash_amount_returns_422(self, auth_token):
        """points_source='cash' بدون conditions.cash_amount_per_point → 422."""
        with app.test_client() as client:
            resp = client.post(
                '/api/bonus-rules',
                json={
                    'name': 'cash_missing_config_test',
                    'rule_type': 'points_based',
                    'bonus_type': 'points_per_unit',
                    'bonus_value': 5.0,
                    'points_source': 'cash',
                    'conditions': {'points_period': 'month'},  # بدون cash_amount_per_point
                },
                headers={'Authorization': auth_token},
            )
        assert resp.status_code == 422, f"توقعنا 422 — {resp.get_json()}"
        body = resp.get_json()
        assert body.get('code') == 'points_source_not_applicable'
        assert 'cash_amount_per_point' in body.get('message', '')

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


# ── Calculator ────────────────────────────────────────────────────────────────

class TestPointsSourceCalculator:

    def test_resolve_points_source_defaults_to_gold_when_null(self):
        """_resolve_points_source يُعيد 'gold' عند points_source=None."""
        class _MockRule:
            points_source = None
        assert _resolve_points_source(_MockRule()) == 'gold'

    def test_resolve_points_source_respects_cash(self):
        """_resolve_points_source يُعيد 'cash' عند points_source='cash'."""
        class _MockRule:
            points_source = 'cash'
        assert _resolve_points_source(_MockRule()) == 'cash'

    def test_gold_source_reads_profit_gold(self, points_rule_gold):
        """
        قاعدة points_source='gold' → الـ inputs يحتوي على total_profit_gold_g و points_per_gram.
        نتحقق من بنية calculation_snapshot دون الحاجة لفواتير حقيقية (الموظف بدون فواتير).
        """
        with app.app_context():
            emp = Employee.query.filter_by(is_active=True).first()
            rule = BonusRule.query.get(points_rule_gold)

            # نُعدّل min_points=0 حتى لا يُفلتر بسبب الصفر
            rule.conditions = {'points_period': 'month', 'min_points': 0}
            db.session.commit()

            with patch('bonus_calculator.get_race_points_per_gram', return_value=10.0):
                result = BonusCalculator.calculate_points_bonus(
                    emp, rule,
                    date(2026, 6, 1), date(2026, 6, 30),
                )

            # قد يكون None (لا فواتير/لا ربح) — نتحقق من بنية الـ inputs إذا وُجد نتيجة
            # أو نُنشئ مكافأة ثابتة (fixed) للتحقق من المسار
            rule.bonus_type = 'fixed'
            rule.bonus_value = 100.0
            db.session.commit()

            with patch('bonus_calculator.get_race_points_per_gram', return_value=10.0):
                result = BonusCalculator.calculate_points_bonus(
                    emp, rule,
                    date(2026, 6, 1), date(2026, 6, 30),
                )

        assert result is not None, 'fixed bonus يجب أن يُنتج نتيجة حتى بدون نقاط'
        _raw, _amt, calc_data, _min, _max = result
        assert calc_data['points_source'] == 'gold'
        assert 'points_per_gram' in calc_data
        assert 'total_profit_gold_g' in calc_data
        assert 'cash_amount_per_point' not in calc_data

    def test_null_source_behaves_like_gold(self, points_rule_null_source):
        """
        قاعدة points_source=None → نفس مفاتيح gold في calculation_data.
        """
        with app.app_context():
            emp = Employee.query.filter_by(is_active=True).first()
            rule = BonusRule.query.get(points_rule_null_source)
            rule.bonus_type = 'fixed'
            rule.bonus_value = 50.0
            rule.conditions = {'points_period': 'month', 'min_points': 0}
            db.session.commit()

            with patch('bonus_calculator.get_race_points_per_gram', return_value=10.0):
                result = BonusCalculator.calculate_points_bonus(
                    emp, rule,
                    date(2026, 6, 1), date(2026, 6, 30),
                )

        assert result is not None
        _raw, _amt, calc_data, _min, _max = result
        assert calc_data['points_source'] == 'gold'
        assert 'points_per_gram' in calc_data
        assert 'cash_amount_per_point' not in calc_data

    def test_cash_source_reads_profit_cash(self, points_rule_cash):
        """
        قاعدة points_source='cash' → الـ inputs يحتوي على total_profit_cash و cash_amount_per_point.
        """
        with app.app_context():
            emp = Employee.query.filter_by(is_active=True).first()
            rule = BonusRule.query.get(points_rule_cash)
            rule.bonus_type = 'fixed'
            rule.bonus_value = 200.0
            rule.conditions = {'cash_amount_per_point': 100.0, 'points_period': 'month', 'min_points': 0}
            db.session.commit()

            result = BonusCalculator.calculate_points_bonus(
                emp, rule,
                date(2026, 6, 1), date(2026, 6, 30),
            )

        assert result is not None
        _raw, _amt, calc_data, _min, _max = result
        assert calc_data['points_source'] == 'cash'
        assert 'cash_amount_per_point' in calc_data
        assert 'total_profit_cash' in calc_data
        assert 'points_per_gram' not in calc_data
        assert 'total_profit_gold_g' not in calc_data


# ── Snapshots ─────────────────────────────────────────────────────────────────

class TestPointsSourceSnapshots:

    def test_rule_snapshot_records_points_source(self, points_rule_cash):
        """rule_snapshot يحتوي على points_source بقيمته الصحيحة."""
        with app.app_context():
            rule = BonusRule.query.get(points_rule_cash)
            snap = rule.to_snapshot()

        assert 'points_source' in snap, 'to_snapshot() يجب أن يُصدّر points_source'
        assert snap['points_source'] == 'cash'

    def test_calculation_snapshot_inputs_record_points_source(self, points_rule_cash):
        """calculation_snapshot.inputs يسجّل points_source من مسار الاحتساب."""
        with app.app_context():
            emp = Employee.query.filter_by(is_active=True).first()
            rule = BonusRule.query.get(points_rule_cash)
            rule.bonus_type = 'fixed'
            rule.bonus_value = 150.0
            rule.conditions = {'cash_amount_per_point': 100.0, 'points_period': 'month', 'min_points': 0}
            db.session.commit()

            bonus = BonusCalculator.calculate_bonus(
                emp, rule,
                date(2026, 7, 1), date(2026, 7, 31),
            )

        assert bonus is not None
        snap = bonus.calculation_snapshot
        assert snap is not None
        assert snap['inputs']['points_source'] == 'cash'
        assert 'cash_amount_per_point' in snap['inputs']
