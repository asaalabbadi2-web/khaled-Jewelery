"""Numeric coercion — Arabic/Persian digit normalization and safe float conversion."""
from __future__ import annotations

_EASTERN = '٠١٢٣٤٥٦٧٨٩'
_PERSIAN = '۰۱۲۳۴۵۶۷۸۹'


def normalize_number(text: str) -> str:
    """Replace Eastern/Persian-Arabic digits with ASCII equivalents."""
    for i in range(10):
        text = text.replace(_EASTERN[i], str(i))
        text = text.replace(_PERSIAN[i], str(i))
    return text


def coerce_float(value: object, default: float = 0.0) -> float:
    """Safely coerce *value* to float; return *default* on failure."""
    if value in (None, '', False):
        return default
    try:
        return float(normalize_number(str(value)))
    except Exception:
        try:
            return float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default
