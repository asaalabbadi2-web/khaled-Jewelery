from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

from sqlalchemy import func

# Allow running as a script (python devtools/...) while importing backend modules.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import app
from category_weight_tracking import (
    get_category_weight_balances,
    record_category_weight_movements_for_invoice_payload,
)
from models import Category, CategoryWeightMovement, Invoice, SafeBox, db


def main() -> None:
    with app.app_context():
        print('db_uri:', app.config.get('SQLALCHEMY_DATABASE_URI'))
        gold_safes = SafeBox.query.filter_by(safe_type='gold', is_active=True).all()
        print('gold_safes:', [(s.id, s.name, s.karat) for s in gold_safes])

        cat = Category.query.filter_by(name='تصنيف تجريبي').first()
        if not cat:
            cat = Category(name='تصنيف تجريبي')
            db.session.add(cat)
            db.session.flush()

        next_invoice_type_id = (
            db.session.query(func.max(Invoice.invoice_type_id))
            .filter(Invoice.invoice_type == 'بيع')
            .scalar()
            or 0
        )

        inv = Invoice(
            invoice_type_id=int(next_invoice_type_id) + 1,
            invoice_type='بيع',
            date=datetime.utcnow(),
            total=0.0,
            is_posted=True,
            posted_at=datetime.utcnow(),
            posted_by='devtools',
        )
        db.session.add(inv)
        db.session.flush()

        before = CategoryWeightMovement.query.count()
        res = record_category_weight_movements_for_invoice_payload(
            inv.id,
            items_payload=[
                {
                    'category_id': cat.id,
                    'weight': 10.0,
                    'karat': 21,
                    'quantity': 1,
                    'name': 'سطر تصنيف',
                }
            ],
        )
        db.session.commit()
        after = CategoryWeightMovement.query.count()

        print('created:', after - before)
        print('res:', res)
        print('balances:', get_category_weight_balances())


if __name__ == '__main__':
    main()
