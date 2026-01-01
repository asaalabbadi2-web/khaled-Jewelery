#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Tests for invoice weight calculations, especially manual items."""

from datetime import datetime

from app import app
from models import db, Invoice, InvoiceItem


def test_manual_invoice_items_included_in_total_weight():
    """Manual invoice items without Item FK should contribute to total weight."""
    with app.app_context():
        try:
            invoice = Invoice(
                invoice_type='بيع',
                invoice_type_id=999_999,
                date=datetime.utcnow(),
                total=0.0,
            )
            db.session.add(invoice)
            db.session.flush()

            db.session.add(InvoiceItem(
                invoice_id=invoice.id,
                item_id=None,  # manual item
                name='خاتم يدوي',
                quantity=2,
                price=0.0,
                karat=18,
                weight=1.5,  # لكل قطعة 1.5 جم عيار 18
                wage=0.0,
                net=0.0,
                tax=0.0,
            ))
            db.session.flush()

            calculated_weight = invoice.calculate_total_weight()
            # كل قطعة 1.5 جم عيار 18 → تعادل (1.5 * 18 / 21) جم رئيسي
            expected_per_item = (1.5 * 18) / 21
            assert abs(calculated_weight - (expected_per_item * 2)) < 1e-6
        finally:
            db.session.rollback()
