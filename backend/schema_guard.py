"""Runtime safeguards for keeping critical schema pieces in sync.

These helpers are intentionally lightweight so the app can self-heal when
new columns are introduced but existing deployments have not yet executed
Alembic migrations. They should only be used for additive changes that are
safe to apply with simple `ALTER TABLE ... ADD COLUMN ... DEFAULT ...`.
"""
from __future__ import annotations

import logging
from typing import Iterable

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

LOGGER = logging.getLogger(__name__)


def _ensure_columns(
    engine: Engine,
    table: str,
    columns: Iterable[tuple[str, str, str]],
) -> list[str]:
    """Ensure each ``(name, ddl, default)`` column tuple exists on ``table``.

    Parameters
    ----------
    engine:
        Bound SQLAlchemy engine to use for inspection and DDL execution.
    table:
        Table name to modify.
    columns:
        Iterable of tuples describing ``(column_name, ddl_type, default)``.

    Returns
    -------
    list[str]
        Names of columns that were added during this invocation.
    """
    added: list[str] = []
    with engine.connect() as connection:
        inspector = inspect(connection)
        existing = {column["name"] for column in inspector.get_columns(table)}
        for name, ddl_type, default in columns:
            if name in existing:
                continue
            LOGGER.warning(
                "Missing column %s.%s detected at runtime; applying lightweight migration",
                table,
                name,
            )
            ddl = text(
                f"ALTER TABLE {table} ADD COLUMN {name} {ddl_type} DEFAULT {default}"
            )
            connection.execute(ddl)
            added.append(f"{table}.{name}")
    return added


def _log_added(columns_added: list[str]) -> None:
    if columns_added:
        LOGGER.info("Auto-added missing columns: %s", ", ".join(columns_added))


def ensure_profit_weight_columns(engine: Engine) -> None:
    """Backfill profit-weight columns if Alembic migration hasn't run yet."""
    columns_added: list[str] = []
    try:
        columns_added.extend(
            _ensure_columns(
                engine,
                "invoice",
                [("profit_weight_price_per_gram", "FLOAT", "0")],
            )
        )
        columns_added.extend(
            _ensure_columns(
                engine,
                "invoice_item",
                [
                    ("avg_cost_per_gram_snapshot", "FLOAT", "0"),
                    ("profit_cash", "FLOAT", "0"),
                    ("profit_weight", "FLOAT", "0"),
                    ("profit_weight_price_per_gram", "FLOAT", "0"),
                ],
            )
        )
    except SQLAlchemyError as exc:
        LOGGER.error("Auto schema guard failed: %s", exc)
        return

    _log_added(columns_added)


def ensure_settings_columns(engine: Engine) -> None:
    """Ensure newer settings columns exist for legacy databases."""
    columns_added: list[str] = []
    try:
        columns_added.extend(
            _ensure_columns(
                engine,
                "settings",
                [("weight_closing_settings", "TEXT", "'{}'")],
            )
        )
    except SQLAlchemyError as exc:
        LOGGER.error("Auto schema guard failed: %s", exc)
        return

    _log_added(columns_added)


def ensure_weight_closing_columns(engine: Engine) -> None:
    """Add invoice weight-closing summary columns when missing."""
    columns_added: list[str] = []
    try:
        columns_added.extend(
            _ensure_columns(
                engine,
                "invoice",
                [
                    ("weight_closing_status", "VARCHAR(20)", "'not_initialized'"),
                    ("weight_closing_main_karat", "FLOAT", "21"),
                    ("weight_closing_total_weight", "FLOAT", "0"),
                    ("weight_closing_executed_weight", "FLOAT", "0"),
                    ("weight_closing_remaining_weight", "FLOAT", "0"),
                    ("weight_closing_close_price", "FLOAT", "0"),
                    ("weight_closing_order_number", "VARCHAR(30)", "NULL"),
                    ("weight_closing_price_source", "VARCHAR(20)", "NULL"),
                ],
            )
        )
    except SQLAlchemyError as exc:
        LOGGER.error("Auto schema guard failed: %s", exc)
        return

    _log_added(columns_added)


def ensure_invoice_tax_columns(engine: Engine) -> None:
    """Ensure invoice-level tax breakdown columns exist."""
    columns_added: list[str] = []
    try:
        columns_added.extend(
            _ensure_columns(
                engine,
                "invoice",
                [
                    ("gold_subtotal", "FLOAT", "0"),
                    ("wage_subtotal", "FLOAT", "0"),
                    ("gold_tax_total", "FLOAT", "0"),
                    ("wage_tax_total", "FLOAT", "0"),
                ],
            )
        )
    except SQLAlchemyError as exc:
        LOGGER.error("Auto schema guard failed: %s", exc)
        return

    _log_added(columns_added)
