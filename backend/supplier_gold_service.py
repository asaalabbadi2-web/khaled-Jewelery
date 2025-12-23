"""Utility service to track supplier gold balances and settlements."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional

from models import (
    Supplier,
    SupplierGoldTransaction,
    Invoice,
    db,
)


class SupplierGoldService:
    """Encapsulates supplier gold balance calculations."""

    @staticmethod
    def _get_supplier(supplier_id: int) -> Supplier:
        supplier = Supplier.query.get(supplier_id)
        if not supplier:
            raise ValueError(f"Supplier #{supplier_id} not found")
        return supplier

    @staticmethod
    def _apply_balance_change(
        supplier: Supplier,
        weight_delta: float,
        cash_delta: float,
    ) -> None:
        supplier.gold_balance_weight = (supplier.gold_balance_weight or 0.0) + (weight_delta or 0.0)
        supplier.gold_balance_cash_equivalent = (
            supplier.gold_balance_cash_equivalent or 0.0
        ) + (cash_delta or 0.0)
        supplier.last_gold_transaction_date = datetime.utcnow()

    @staticmethod
    def record_purchase(
        supplier_id: int,
        invoice_id: Optional[int],
        gold_weight_21k: float,
        price_per_gram: float,
        manufacturing_wage_per_gram: float = 0.0,
        transaction_type: str = 'purchase',
        auto_commit: bool = True,
    ) -> SupplierGoldTransaction:
        supplier = SupplierGoldService._get_supplier(supplier_id)
        invoice = Invoice.query.get(invoice_id) if invoice_id else None

        cash_amount = gold_weight_21k * (price_per_gram or 0.0)
        transaction = SupplierGoldTransaction(
            supplier_id=supplier.id,
            invoice_id=invoice.id if invoice else None,
            transaction_type=transaction_type,
            gold_weight=gold_weight_21k,
            price_per_gram=price_per_gram or 0.0,
            manufacturing_wage_per_gram=manufacturing_wage_per_gram or 0.0,
            cash_amount=cash_amount,
        )

        db.session.add(transaction)
        SupplierGoldService._apply_balance_change(supplier, gold_weight_21k, cash_amount)
        if auto_commit:
            db.session.commit()
        else:
            db.session.flush()
        return transaction

    @staticmethod
    def settle_with_gold(
        supplier_id: int,
        gold_weight_21k: float,
        settlement_price_per_gram: float,
        journal_entry_id: Optional[int] = None,
        notes: Optional[str] = None,
        auto_commit: bool = True,
    ) -> SupplierGoldTransaction:
        supplier = SupplierGoldService._get_supplier(supplier_id)
        cash_equivalent = gold_weight_21k * (settlement_price_per_gram or 0.0)

        transaction = SupplierGoldTransaction(
            supplier_id=supplier.id,
            journal_entry_id=journal_entry_id,
            transaction_type='settlement_gold',
            gold_weight=gold_weight_21k,
            price_per_gram=settlement_price_per_gram or 0.0,
            cash_amount=cash_equivalent,
            settlement_price_per_gram=settlement_price_per_gram,
            settlement_cash_amount=cash_equivalent,
            settlement_gold_weight=gold_weight_21k,
            notes=notes,
        )
        db.session.add(transaction)

        SupplierGoldService._apply_balance_change(supplier, -gold_weight_21k, -cash_equivalent)
        if auto_commit:
            db.session.commit()
        else:
            db.session.flush()
        return transaction

    @staticmethod
    def settle_with_cash(
        supplier_id: int,
        cash_amount: float,
        reference_gold_price: float,
        journal_entry_id: Optional[int] = None,
        notes: Optional[str] = None,
        auto_commit: bool = True,
    ) -> SupplierGoldTransaction:
        supplier = SupplierGoldService._get_supplier(supplier_id)
        if not reference_gold_price:
            raise ValueError('reference_gold_price must be greater than zero for cash settlements')

        gold_equivalent = cash_amount / reference_gold_price

        transaction = SupplierGoldTransaction(
            supplier_id=supplier.id,
            journal_entry_id=journal_entry_id,
            transaction_type='settlement_cash',
            gold_weight=gold_equivalent,
            price_per_gram=reference_gold_price,
            cash_amount=cash_amount,
            settlement_price_per_gram=reference_gold_price,
            settlement_cash_amount=cash_amount,
            settlement_gold_weight=gold_equivalent,
            notes=notes,
        )
        db.session.add(transaction)

        SupplierGoldService._apply_balance_change(supplier, -gold_equivalent, -cash_amount)
        if auto_commit:
            db.session.commit()
        else:
            db.session.flush()
        return transaction

    @staticmethod
    def get_supplier_balance(supplier_id: int) -> Dict[str, float]:
        supplier = SupplierGoldService._get_supplier(supplier_id)
        return {
            'supplier_id': supplier.id,
            'gold_balance_weight': supplier.gold_balance_weight or 0.0,
            'gold_balance_cash_equivalent': supplier.gold_balance_cash_equivalent or 0.0,
            'last_gold_transaction_date': supplier.last_gold_transaction_date.isoformat()
            if supplier.last_gold_transaction_date
            else None,
        }