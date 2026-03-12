import clearing_settlement_scheduler
from app import app


def test_run_auto_clearing_settlements_now_endpoint(auth_headers, monkeypatch):
    called = {'count': 0}

    class _FakeScheduler:
        def process_due_settlements(self):
            called['count'] += 1

    monkeypatch.setattr(
        clearing_settlement_scheduler,
        'get_clearing_settlement_scheduler',
        lambda app_obj: _FakeScheduler(),
    )

    with app.test_client() as client:
        response = client.post(
            '/api/clearing/settlements/auto-run',
            json={},
            headers=auth_headers,
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['success'] is True
    assert 'enabled_methods' in payload
    assert called['count'] == 1