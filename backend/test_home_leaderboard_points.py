from datetime import datetime

from app import app
from models import db, Employee, Invoice, InvoiceItem


def _create_posted_sale(
    employee_id: int,
    *,
    invoice_type_id: int,
    earned_main_karat_g: float,
    weight_g: float = 0.0,
    karat: float = 21.0,
) -> Invoice:
    inv = Invoice(
        invoice_type_id=invoice_type_id,
        invoice_type='بيع',
        employee_id=employee_id,
        date=datetime.now(),
        total=0.0,
        is_posted=True,
        profit_gold=float(earned_main_karat_g),
    )
    db.session.add(inv)
    db.session.flush()  # ensure inv.id

    db.session.add(
        InvoiceItem(
            invoice_id=inv.id,
            item_id=None,
            category_id=None,
            name='manual',
            quantity=1,
            price=0.0,
            karat=float(karat),
            weight=float(weight_g),
            wage=0.0,
            net=0.0,
            tax=0.0,
        )
    )

    return inv


def test_home_leaderboard_points_uses_main_karat_equivalent(auth_headers):
    with app.app_context():
        emp = Employee.query.first()
        assert emp is not None

        # Earned gold weight is stored on the invoice as main-karat grams (profit_gold).
        # Points = earned_main_karat_g * 10.
        _create_posted_sale(
            emp.id,
            invoice_type_id=101,
            earned_main_karat_g=(18.0 / 21.0),
            # Add a big sold weight to ensure leaderboard does NOT use it for points.
            weight_g=100.0,
            karat=24.0,
        )
        _create_posted_sale(
            emp.id,
            invoice_type_id=102,
            earned_main_karat_g=(24.0 / 21.0),
            weight_g=50.0,
            karat=18.0,
        )

        db.session.commit()

    with app.test_client() as client:
        resp = client.get(
            '/api/home/leaderboard',
            query_string={'period': 'today', 'metric': 'points'},
            headers=auth_headers,
        )

    assert resp.status_code == 200
    payload = resp.get_json()

    assert payload.get('metric') == 'points'
    ranking = payload.get('ranking') or []
    assert len(ranking) >= 1

    first = ranking[0]
    assert first.get('count') == 2
    assert first.get('score') == 20.0
    assert first.get('share') == 1.0


def test_home_leaderboard_points_rounds_after_employee_total(auth_headers):
    emp_id = None
    with app.app_context():
        emp = Employee(
            employee_code='EMP-PTS-ROUND',
            name='موظف تقريبي',
            salary=0.0,
            is_active=True,
        )
        db.session.add(emp)
        db.session.flush()
        emp_id = emp.id

        _create_posted_sale(
            emp.id,
            invoice_type_id=201,
            earned_main_karat_g=0.04,
        )
        _create_posted_sale(
            emp.id,
            invoice_type_id=202,
            earned_main_karat_g=0.04,
        )

        db.session.commit()

    with app.test_client() as client:
        resp = client.get(
            '/api/home/leaderboard',
            query_string={'period': 'today', 'metric': 'points'},
            headers=auth_headers,
        )

    assert resp.status_code == 200
    payload = resp.get_json()

    ranking = payload.get('ranking') or []
    assert len(ranking) >= 1
    employee_row = next((row for row in ranking if row.get('id') == emp_id), None)
    assert employee_row is not None
    assert employee_row.get('score') == 1.0

