import json

from app import app
from models import db, Settings


def _clear_settings_rows():
    Settings.query.delete()
    db.session.commit()


def test_settings_put_accepts_sales_race_settings_as_json_string():
    with app.app_context():
        _clear_settings_rows()

    payload = {
        'sales_race_settings': json.dumps(
            {
                'enabled': True,
                'default_period': 'today',
                'show_sales_amount_per_employee': True,
            },
            ensure_ascii=False,
        )
    }

    with app.test_client() as client:
        response = client.put('/api/settings', json=payload)
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, dict)
        assert data['sales_race_settings']['show_sales_amount_per_employee'] is True

    with app.app_context():
        row = Settings.query.order_by(Settings.id.desc()).first()
        assert row is not None
        assert row.sales_race_settings is not None
        decoded = json.loads(row.sales_race_settings)
        assert decoded.get('show_sales_amount_per_employee') is True


def test_settings_singleton_dedupes_multiple_rows_deterministically():
    with app.app_context():
        _clear_settings_rows()
        s1 = Settings(main_karat=21)
        s2 = Settings(main_karat=22)
        db.session.add_all([s1, s2])
        db.session.commit()
        assert Settings.query.count() == 2

    with app.test_client() as client:
        response = client.get('/api/settings')
        assert response.status_code == 200
        data = response.get_json()
        assert data['main_karat'] == 22

    with app.app_context():
        assert Settings.query.count() == 1
        remaining = Settings.query.first()
        assert remaining is not None
        assert remaining.main_karat == 22
