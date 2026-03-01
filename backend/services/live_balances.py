from __future__ import annotations

from typing import Dict, Iterable

from sqlalchemy import func, inspect

from models import db, JournalEntry, JournalEntryLine


_DB_COLUMN_CACHE: dict[tuple[str, str], bool] = {}


def _db_has_column(table_name: str, column_name: str) -> bool:
    key = (table_name, column_name)
    cached = _DB_COLUMN_CACHE.get(key)
    if cached is not None:
        return cached

    try:
        columns = inspect(db.engine).get_columns(table_name)
        exists = any((c.get("name") == column_name) for c in (columns or []))
    except Exception:
        exists = False

    _DB_COLUMN_CACHE[key] = exists
    return exists


def live_balances_by_account_ids(account_ids: Iterable[int]) -> Dict[int, dict]:
    """Compute live balances for multiple accounts from journal lines.

    Canonical source: JournalEntryLine joined to JournalEntry.

    Filters:
      - non-deleted lines and entries
      - prefer non-draft entries when available; else fall back to is_posted

    Returns:
      {account_id: {'cash': float, '18k': float, '21k': float, '22k': float, '24k': float}}
    """
    ids = [int(x) for x in (account_ids or []) if x is not None]
    if not ids:
        return {}

    jl_filters = [
        JournalEntry.is_deleted == False,
        JournalEntryLine.is_deleted == False,
    ]

    # Always require posted entries for accurate balances.
    if _db_has_column("journal_entry", "is_posted"):
        jl_filters.append(JournalEntry.is_posted == True)

    # Additionally exclude drafts when the column exists.
    if _db_has_column("journal_entry", "is_draft"):
        jl_filters.append(JournalEntry.is_draft == False)

    rows = (
        db.session.query(
            JournalEntryLine.account_id.label("account_id"),
            (
                func.coalesce(func.sum(JournalEntryLine.cash_debit), 0.0)
                - func.coalesce(func.sum(JournalEntryLine.cash_credit), 0.0)
            ).label("cash"),
            (
                func.coalesce(func.sum(JournalEntryLine.debit_18k), 0.0)
                - func.coalesce(func.sum(JournalEntryLine.credit_18k), 0.0)
            ).label("b18"),
            (
                func.coalesce(func.sum(JournalEntryLine.debit_21k), 0.0)
                - func.coalesce(func.sum(JournalEntryLine.credit_21k), 0.0)
            ).label("b21"),
            (
                func.coalesce(func.sum(JournalEntryLine.debit_22k), 0.0)
                - func.coalesce(func.sum(JournalEntryLine.credit_22k), 0.0)
            ).label("b22"),
            (
                func.coalesce(func.sum(JournalEntryLine.debit_24k), 0.0)
                - func.coalesce(func.sum(JournalEntryLine.credit_24k), 0.0)
            ).label("b24"),
        )
        .join(JournalEntry)
        .filter(JournalEntryLine.account_id.in_(ids))
        .filter(*jl_filters)
        .group_by(JournalEntryLine.account_id)
        .all()
    )

    out: Dict[int, dict] = {}
    for r in rows:
        try:
            account_id = int(getattr(r, "account_id"))
        except Exception:
            continue

        out[account_id] = {
            "cash": float(getattr(r, "cash", 0.0) or 0.0),
            "18k": float(getattr(r, "b18", 0.0) or 0.0),
            "21k": float(getattr(r, "b21", 0.0) or 0.0),
            "22k": float(getattr(r, "b22", 0.0) or 0.0),
            "24k": float(getattr(r, "b24", 0.0) or 0.0),
        }

    for account_id in ids:
        out.setdefault(account_id, {"cash": 0.0, "18k": 0.0, "21k": 0.0, "22k": 0.0, "24k": 0.0})

    return out
