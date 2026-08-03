"""
test_bonus_phase4_flags.py
===========================
اختبارات Phase 4 — Feature Flags لأنواع attendance و performance.

الاختبارات الخمسة:
  1. إنشاء قاعدة attendance عند تعطيل الميزة → 422 + code=bonus_type_disabled
  2. إنشاء قاعدة performance عند تعطيل الميزة → 422 + code=bonus_type_disabled
  3. إنشاء القاعدة بعد تفعيل Feature Flag → 201 (ينجح)
  4. Calculator يتجاوز قاعدة attendance المعطَّلة ولا ينشئ EmployeeBonus
  5. إعادة تفعيل Flag تُعيد القاعدة للعمل دون Migration أو تعديل بيانات
"""

import pytest
from datetime import date, datetime

from app import app
from models import db, Settings, Employee, BonusRule, EmployeeBonus
from bonus_calculator import BonusCalculator
from core.settings import _get_settings_singleton


# ── Helpers ───────────────────────────────────────────────────────────────────

def _set_flags(attendance: bool, performance: bool):
    """يضبط Feature Flags مباشرة في DB."""
    with app.app_context():
        s = _get_settings_singleton(create_if_missing=True)
        s.bonus_attendance_enabled = attendance
        s.bonus_performance_enabled = performance
        db.session.commit()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_flags():
    """يُعيد الـ flags إلى الوضع الآمن (false) قبل وبعد كل اختبار."""
    _set_flags(False, False)
    yield
    _set_flags(False, False)


@pytest.fixture
def auth_token():
    with app.app_context():
        from auth_decorators import generate_token
        from models import User
        admin = User.query.filter_by(username='admin').first()
        assert admin
        return f'Bearer {generate_token(admin)}'


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestFeatureFlagRouteGuard:
    """Guards في POST /bonus-rules و PUT /bonus-rules/{id}."""

    def test_create_attendance_rule_disabled_returns_422(self, auth_token):
        """إنشاء قاعدة attendance عند تعطيل الميزة → 422."""
        with app.test_client() as client:
            resp = client.post(
                '/api/bonus-rules',
                json={
                    'name': 'اختبار attendance',
                    'rule_type': 'attendance',
                    'bonus_type': 'fixed',
                    'bonus_value': 300.0,
                },
                headers={'Authorization': auth_token},
            )

        assert resp.status_code == 422, f"توقعنا 422 — {resp.get_json()}"
        body = resp.get_json()
        assert body.get('code') == 'bonus_type_disabled'
        assert 'Attendance' in body.get('message', '')

    def test_create_performance_rule_disabled_returns_422(self, auth_token):
        """إنشاء قاعدة performance عند تعطيل الميزة → 422."""
        with app.test_client() as client:
            resp = client.post(
                '/api/bonus-rules',
                json={
                    'name': 'اختبار performance',
                    'rule_type': 'performance',
                    'bonus_type': 'fixed',
                    'bonus_value': 400.0,
                },
                headers={'Authorization': auth_token},
            )

        assert resp.status_code == 422, f"توقعنا 422 — {resp.get_json()}"
        body = resp.get_json()
        assert body.get('code') == 'bonus_type_disabled'
        assert 'Performance' in body.get('message', '')

    def test_create_attendance_rule_enabled_returns_201(self, auth_token):
        """إنشاء قاعدة attendance بعد تفعيل Flag → 201."""
        _set_flags(attendance=True, performance=False)

        with app.test_client() as client:
            resp = client.post(
                '/api/bonus-rules',
                json={
                    'name': 'attendance مُفعَّل',
                    'rule_type': 'attendance',
                    'bonus_type': 'fixed',
                    'bonus_value': 500.0,
                },
                headers={'Authorization': auth_token},
            )

        assert resp.status_code == 201, (
            f"توقعنا 201 بعد تفعيل Flag — {resp.get_json()}"
        )
        body = resp.get_json()
        assert body['rule']['rule_type'] == 'attendance'


class TestFeatureFlagCalculator:
    """Feature Flag في محرك الاحتساب."""

    def test_disabled_attendance_rule_skipped_in_calculator(self):
        """
        قاعدة attendance موجودة في DB + Flag=false
        → calculate_all_bonuses_for_period لا ينشئ EmployeeBonus.
        """
        with app.app_context():
            emp = Employee.query.first()

            # ننشئ القاعدة مباشرة في DB (نتجاوز الـ route guard)
            rule = BonusRule(
                name='attendance_skipped_test',
                rule_type='attendance',
                bonus_type='fixed',
                bonus_value=750.0,
                is_active=True,
                created_by='test',
            )
            db.session.add(rule)
            db.session.commit()
            rule_id = rule.id

            # Flag=false (الافتراضي) — يجب أن يتجاوز المحرك هذه القاعدة
            bonuses = BonusCalculator.calculate_all_bonuses_for_period(
                date(2026, 10, 1), date(2026, 10, 31),
                employee_ids=[emp.id],
                rule_ids=[rule_id],
            )

        assert len(bonuses) == 0, (
            f"توقعنا 0 مكافأة (القاعدة متجاوَزة) — وجدنا {len(bonuses)}"
        )

        with app.app_context():
            saved = EmployeeBonus.query.filter_by(
                bonus_rule_id=rule_id,
                period_start=date(2026, 10, 1),
            ).first()
            assert saved is None, 'يجب ألا تُنشأ EmployeeBonus عند تعطيل الميزة'

    def test_enabling_flag_makes_calculator_produce_bonus(self):
        """
        إعادة تفعيل Flag → المحرك يُنشئ EmployeeBonus دون أي Migration.
        """
        with app.app_context():
            emp = Employee.query.first()

            rule = BonusRule(
                name='attendance_reenabled_test',
                rule_type='attendance',
                bonus_type='fixed',
                bonus_value=600.0,
                is_active=True,
                created_by='test',
            )
            db.session.add(rule)
            db.session.commit()
            rule_id = rule.id

        # نُفعِّل Flag
        _set_flags(attendance=True, performance=False)

        with app.app_context():
            emp = Employee.query.first()
            bonuses = BonusCalculator.calculate_all_bonuses_for_period(
                date(2026, 11, 1), date(2026, 11, 30),
                employee_ids=[emp.id],
                rule_ids=[rule_id],
            )

        assert len(bonuses) >= 1, (
            f"توقعنا مكافأة بعد تفعيل Flag — وجدنا {len(bonuses)}"
        )
        assert bonuses[0].bonus_rule_id == rule_id
        assert bonuses[0].amount == 600.0
