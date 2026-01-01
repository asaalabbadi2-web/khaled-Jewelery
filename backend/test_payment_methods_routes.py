import json

from app import app
from models import db, PaymentMethod, Settings


def _clear_payment_methods():
    PaymentMethod.query.delete()
    db.session.commit()


def _ensure_settings(payment_methods_payload=None):
    settings = Settings.query.first()
    if not settings:
        settings = Settings()
        db.session.add(settings)
        db.session.commit()
        settings = Settings.query.first()

    settings.payment_methods = (
        json.dumps(payment_methods_payload, ensure_ascii=False)
        if payment_methods_payload is not None
        else None
    )
    db.session.commit()
    return settings


def test_active_payment_methods_auto_seed_from_settings():
    with app.app_context():
        _clear_payment_methods()
        _ensure_settings([
            {'name': 'نقداً', 'commission': 0},
            {'name': 'بطاقة', 'commission': 2.5},
        ])

    with app.test_client() as client:
        response = client.get('/api/payment-methods/active')
        assert response.status_code == 200
        payload = response.get_json()
        assert isinstance(payload, list)
        assert len(payload) >= 2
        names = {entry.get('name') for entry in payload}
        assert 'نقداً' in names
        assert 'بطاقة' in names

    with app.app_context():
        assert PaymentMethod.query.count() >= 2


def test_active_payment_methods_seed_from_defaults_when_no_settings_data():
    with app.app_context():
        _clear_payment_methods()
        _ensure_settings(None)

    with app.test_client() as client:
        response = client.get('/api/payment-methods/active')
        assert response.status_code == 200
        payload = response.get_json()
        assert isinstance(payload, list)
        assert len(payload) >= 1

    with app.app_context():
        assert PaymentMethod.query.count() >= 1


def test_payment_methods_reflect_settings_changes_without_manual_reset():
    with app.app_context():
        _clear_payment_methods()
        _ensure_settings([
            {'name': 'نقداً', 'commission': 0},
        ])

    with app.test_client() as client:
        first_response = client.get('/api/payment-methods/active')
        assert first_response.status_code == 200
        first_payload = first_response.get_json()
        assert len(first_payload) == 1
        assert first_payload[0]['name'] == 'نقداً'

    with app.app_context():
        assert PaymentMethod.query.count() == 1
        # تحديث الإعدادات بإضافة وسيلة جديدة وتعديل العمولة
        _ensure_settings([
            {'name': 'نقداً', 'commission': 1.25},
            {'name': 'تحويل فوري', 'commission': 0},
        ])

    with app.test_client() as client:
        second_response = client.get('/api/payment-methods/active')
        assert second_response.status_code == 200
        second_payload = second_response.get_json()
        names = {entry['name'] for entry in second_payload}
        assert names == {'نقداً', 'تحويل فوري'}
        updated_cash = next(item for item in second_payload if item['name'] == 'نقداً')
        assert updated_cash['commission_rate'] == 1.25

    with app.app_context():
        assert PaymentMethod.query.count() == 2
