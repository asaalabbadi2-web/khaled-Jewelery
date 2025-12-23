"""Utilities to keep Office and Supplier records in sync."""
from __future__ import annotations

from typing import Optional

from models import db, Office, Supplier
from code_generator import generate_supplier_code


def ensure_office_supplier(office: Office, *, auto_commit: bool = False) -> Supplier:
    """Ensure the given office has a dedicated supplier record and return it."""
    if not office:
        raise ValueError('office is required to ensure supplier linkage')

    if office.supplier:
        return office.supplier

    supplier = Supplier(
        supplier_code=generate_supplier_code(),
        name=office.name,
        phone=office.phone,
        email=office.email,
        account_category_id=office.account_category_id,
        notes=f'مورد مرتبط بالمكتب {office.office_code}',
        active=office.active,
        balance_cash=0.0,
        balance_gold_18k=0.0,
        balance_gold_21k=0.0,
        balance_gold_22k=0.0,
        balance_gold_24k=0.0,
        gold_balance_weight=0.0,
        gold_balance_cash_equivalent=0.0,
    )
    db.session.add(supplier)
    db.session.flush()

    office.supplier_id = supplier.id
    db.session.add(office)

    if auto_commit:
        db.session.commit()

    return supplier


def ensure_office_supplier_by_id(office_id: int, *, auto_commit: bool = False) -> Optional[Supplier]:
    """Helper that fetches an office by ID and ensures its supplier linkage."""
    office = Office.query.get(office_id)
    if not office:
        return None
    return ensure_office_supplier(office, auto_commit=auto_commit)
