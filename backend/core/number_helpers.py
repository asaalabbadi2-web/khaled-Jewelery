"""Numeric coercion helpers — no business logic, no DB access."""
from __future__ import annotations

from utils import normalize_number


def coerce_float(value, default: float = 0.0) -> float:
    """Safely coerce *value* to float; return *default* on failure."""
    if value in (None, '', False):
        return default
    try:
        return float(normalize_number(str(value)))
    except Exception:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default


# Private alias kept for backward compat with routes/__init__.py re-export.
_coerce_float = coerce_float
