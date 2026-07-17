"""Date/time parsing helpers — no DB access, no business logic."""
from __future__ import annotations

from datetime import date, datetime, time


def parse_iso_date(value, field_name: str = 'date'):
    """Parse *value* to a :class:`date`; raise ``ValueError`` on bad input."""
    if value in (None, ''):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ValueError(f'Invalid {field_name} format. Expected YYYY-MM-DD')


def parse_iso_time(value, field_name: str = 'time'):
    """Parse *value* to a :class:`time`; raise ``ValueError`` on bad input."""
    if value in (None, ''):
        return None
    if isinstance(value, time):
        return value
    if isinstance(value, datetime):
        return value.time()
    if isinstance(value, str):
        for fmt in ('%H:%M', '%H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
            try:
                return datetime.strptime(value, fmt).time()
            except ValueError:
                pass
    raise ValueError(f'قيمة غير صالحة للحقل {field_name}: {value}')


# Private aliases kept for backward compat with routes/__init__.py re-export.
_parse_iso_date = parse_iso_date
_parse_iso_time = parse_iso_time
