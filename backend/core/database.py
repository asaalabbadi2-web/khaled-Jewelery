"""Database introspection helpers — schema-level queries."""
from __future__ import annotations

from models import db

_DB_COLUMN_CACHE: dict[tuple[str, str], bool] = {}


def db_has_column(table_name: str, column_name: str) -> bool:
    """Return True if *table_name* has a column named *column_name*.

    Result is process-cached — safe to call in hot paths.
    """
    key = (table_name, column_name)
    cached = _DB_COLUMN_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        from sqlalchemy import inspect as sa_inspect
        inspector = sa_inspect(db.engine)
        cols = {c.get('name') for c in inspector.get_columns(table_name)}
        exists = column_name in cols
    except Exception:
        exists = False
    _DB_COLUMN_CACHE[key] = exists
    return exists


# Private alias kept for backward compat with routes/__init__.py re-export.
_db_has_column = db_has_column
