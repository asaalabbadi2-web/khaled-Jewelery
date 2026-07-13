from __future__ import annotations

from sqlalchemy import func

from models import db, Account, JournalEntryLine


def get_inventory_average_cost(karat) -> float:
    """Weighted Average Cost for the given karat inventory.

    Hybrid-ledger note: cash is stored on the financial account (1300-1330)
    and weight on the memo account (71300-71330), so both are queried.
    """
    inv_24_cash = '1330' if Account.query.filter_by(account_number='1330').first() else '1340'
    inventory_account_map_cash = {
        '18': '1300',
        '21': '1310',
        '22': '1320',
        '24': inv_24_cash,
    }
    inventory_account_map_weight = {
        '18': '71300',
        '21': '71310',
        '22': '71320',
        '24': '71330',
    }

    cash_account_number = inventory_account_map_cash.get(str(karat))
    weight_account_number = inventory_account_map_weight.get(str(karat))

    if not cash_account_number or not weight_account_number:
        return 0.0

    cash_account = Account.query.filter_by(account_number=cash_account_number).first()
    if not cash_account:
        return 0.0

    cash_result = db.session.query(
        func.coalesce(func.sum(JournalEntryLine.cash_debit), 0).label('total_debit_cash'),
        func.coalesce(func.sum(JournalEntryLine.cash_credit), 0).label('total_credit_cash')
    ).filter(
        JournalEntryLine.account_id == cash_account.id
    ).first()

    total_cash = (cash_result.total_debit_cash or 0) - (cash_result.total_credit_cash or 0)

    weight_account = Account.query.filter_by(account_number=weight_account_number).first()
    if not weight_account:
        return 0.0

    weight_result = db.session.query(
        func.coalesce(func.sum(getattr(JournalEntryLine, f'debit_{karat}k')), 0).label('total_debit_weight'),
        func.coalesce(func.sum(getattr(JournalEntryLine, f'credit_{karat}k')), 0).label('total_credit_weight')
    ).filter(
        JournalEntryLine.account_id == weight_account.id
    ).first()

    total_weight = (weight_result.total_debit_weight or 0) - (weight_result.total_credit_weight or 0)

    if total_weight > 0:
        return round(total_cash / total_weight, 2)
    return 0.0
