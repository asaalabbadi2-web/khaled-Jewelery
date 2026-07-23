"""Alembic migration environment for the Commerce API.

DATABASE_URL is read from the environment variable of the same name — never
from alembic.ini, so credentials never appear in committed config.

Import ALL ORM modules before `target_metadata = Base.metadata` so that
autogenerate comparisons see the complete schema.  New ORM modules must be
added here; omitting one causes autogenerate to propose DROP TABLE for the
missing model, which is the wrong direction.
"""
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# ── Register all ORM models with Base.metadata ───────────────────────────────
# Order does not matter; imports are listed alphabetically.
import yasargold_commerce.infra.notification_orm  # noqa: F401
import yasargold_commerce.infra.order_orm  # noqa: F401
import yasargold_commerce.infra.payment_orm  # noqa: F401
import yasargold_commerce.infra.pos_claim_orm  # noqa: F401
import yasargold_commerce.infra.reconciliation_orm  # noqa: F401
import yasargold_commerce.infra.reservation_orm  # noqa: F401
import yasargold_commerce.infra.shipment_orm  # noqa: F401
import yasargold_commerce.models  # noqa: F401  — category, item, gold_price (ERP mirrors)

from yasargold_commerce.db import Base

# ── Alembic Config ────────────────────────────────────────────────────────────
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL environment variable is required for Alembic migrations.\n"
            "Example: DATABASE_URL=postgresql://commerce:dev@localhost:5434/yasargold_commerce"
        )
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (no live connection — SQL dumped to stdout)."""
    url = _database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations with a live DB connection (standard deploy path)."""
    cfg = config.get_section(config.config_ini_section) or {}
    cfg["sqlalchemy.url"] = _database_url()

    connectable = engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
