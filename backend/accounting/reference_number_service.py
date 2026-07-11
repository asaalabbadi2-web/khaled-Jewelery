"""Journal entry reference number generator — collision-safe sequential numbering.

Extracted from routes.py to break the circular dependency:
  dual_system_helpers → routes._generate_journal_entry_number
"""
from __future__ import annotations

from datetime import datetime


def generate_journal_entry_number(prefix: str = "JE", entry_date: datetime | None = None) -> str:
    """Generate a unique, sequential journal entry number.

    Format: ``{prefix}-{year}-{seq:05d}``.

    - Uses entry_date year (not current year) so backdated entries don't break numbering.
    - Uses MAX(entry_number) rather than COUNT() to avoid duplicates on deletions.
    - Caches per app-context so multiple calls in the same request stay unique pre-commit.

    Backward compatibility: if prefix is a datetime it is treated as entry_date.
    """
    from flask import current_app
    from models import JournalEntry
    db = current_app.extensions['sqlalchemy']

    if isinstance(prefix, datetime):
        entry_date = prefix
        prefix = "JE"

    dt = entry_date or datetime.now()
    year = int(getattr(dt, "year", datetime.now().year))
    prefix_str = str(prefix)
    number_prefix = f"{prefix_str}-{year}-"

    cache: dict | None = None
    try:
        cache = db.session.info.setdefault("_entry_number_seq_cache", {})
    except Exception:
        pass

    if cache is None:
        try:
            from flask import g
            cache = getattr(g, "_entry_number_seq_cache", None)
            if cache is None:
                cache = {}
                setattr(g, "_entry_number_seq_cache", cache)
        except Exception:
            cache = {}

    cache_key = (prefix_str, year)
    last_seq = cache.get(cache_key)

    if last_seq is None:
        row = (
            db.session.query(JournalEntry.entry_number)
            .filter(JournalEntry.entry_number.like(f"{number_prefix}%"))
            .order_by(JournalEntry.entry_number.desc())
            .first()
        )
        if row and row[0]:
            try:
                last_seq = int(str(row[0]).split("-")[-1])
            except Exception:
                last_seq = 0
        else:
            last_seq = 0

    next_seq = int(last_seq) + 1

    while True:
        candidate = f"{number_prefix}{next_seq:05d}"
        exists = (
            db.session.query(JournalEntry.id)
            .filter(JournalEntry.entry_number == candidate)
            .first()
            is not None
        )
        if not exists:
            cache[cache_key] = next_seq
            return candidate
        next_seq += 1
