from __future__ import annotations

from datetime import datetime
from typing import Tuple

from flask import current_app

from dual_system_helpers import create_dual_journal_entry, verify_dual_balance
from models import Account, JournalEntry, db

DEFAULT_WAGE_INVENTORY_ACCOUNT = ("7525", "مخزون أجور مصنعية (وزن)")
DEFAULT_WAGE_RELEASE_ACCOUNT = ("7530", "مصاريف تحرير أجور مصنعية (وزن)")


def _weight_kwargs_for_karat(karat: float | int, weight: float, side: str = "debit") -> dict:
    if weight is None or weight <= 0:
        return {}
    karat_key = str(int(round(float(karat or 21))))
    suffix_map = {
        "18": "18k",
        "21": "21k",
        "22": "22k",
        "24": "24k",
    }
    suffix = suffix_map.get(karat_key)
    if not suffix:
        suffix = "21k"
    side_name = side if side in ("debit", "credit") else "debit"
    return {f"{side_name}_{suffix}": round(float(weight), 6)}


def _ensure_memo_account(account_data: Tuple[str, str]) -> Account:
    number, name = account_data
    account = Account.query.filter_by(account_number=number).first()
    if account:
        return account

    account = Account(
        account_number=number,
        name=name,
        type="Memo",
        transaction_type="gold",
        tracks_weight=False,
    )
    db.session.add(account)
    db.session.flush()
    return account


def create_wage_weight_release_journal(weight_grams: float, note: str | None = None, karat: float | int = 21) -> JournalEntry:
    """Release capitalized manufacturing wages as memo weight expense."""
    if weight_grams is None:
        raise ValueError("weight_grams is required")

    try:
        weight_value = round(float(weight_grams), 6)
    except (TypeError, ValueError):
        raise ValueError("weight_grams must be a number")

    if weight_value <= 0:
        raise ValueError("weight_grams must be greater than zero")

    wage_inventory_account = _ensure_memo_account(DEFAULT_WAGE_INVENTORY_ACCOUNT)
    wage_release_account = _ensure_memo_account(DEFAULT_WAGE_RELEASE_ACCOUNT)

    description = (note or "Release wage weight").strip()
    now = datetime.utcnow()

    journal_entry = JournalEntry(
        date=now,
        description=description,
        entry_type='تسوية وزنية',
        reference_type='wage_release',
        is_posted=True,
        posted_at=now,
        posted_by='system',
        created_by='system'
    )
    db.session.add(journal_entry)
    db.session.flush()

    credit_kwargs = _weight_kwargs_for_karat(karat, weight_value, side='credit')
    debit_kwargs = _weight_kwargs_for_karat(karat, weight_value, side='debit')

    create_dual_journal_entry(
        journal_entry_id=journal_entry.id,
        account_id=wage_inventory_account.id,
        description=description,
        **credit_kwargs
    )

    create_dual_journal_entry(
        journal_entry_id=journal_entry.id,
        account_id=wage_release_account.id,
        description=description,
        **debit_kwargs
    )

    balance_state = verify_dual_balance(journal_entry.id)
    if not balance_state.get('balanced', True):
        current_app.logger.warning(
            "Wage weight release journal %s imbalance: %s",
            journal_entry.id,
            balance_state.get('errors')
        )

    db.session.commit()
    return journal_entry
