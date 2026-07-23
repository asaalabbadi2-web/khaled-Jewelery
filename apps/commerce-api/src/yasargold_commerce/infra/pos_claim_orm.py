"""ORM model for POS claims — the terminal fix for INV-4 (ADR-016 §H-series H1).

A POS claim is an atomic intent: the ERP requests exclusive right to sell
item X before opening its own database transaction. Commerce grants the claim
inside its own transaction using SELECT FOR UPDATE + a partial unique index,
so at most one ACTIVE claim per item can exist at any instant.

Lifecycle:
    ACTIVE    — claim is live; ERP must complete its sale before expires_at
    CONFIRMED — ERP committed the invoice; the item is sold
    RELEASED  — ERP rolled back; the claim is voluntarily returned early
    EXPIRED   — claim reached expires_at without confirmation (ERP crash, timeout)

Expiry is enforced at query time, not by a background job. Any check for an
ACTIVE claim must also filter expires_at > now().

Concurrency — two-layer defence (mirrors INV-6 pattern for reservations):

  Layer 1 — SELECT FOR UPDATE (in pos_claims.py):
    The claim router uses SELECT FOR UPDATE on both ReservationRow (if present)
    and PosClaimRow (if present). This serialises concurrent requests that read
    the same row. NOWAIT semantics will be added in the PostgreSQL migration so
    a blocked request fails immediately rather than queuing.

  Layer 2 — Partial Unique Index:
    CREATE UNIQUE INDEX ix_pos_claims_one_active_per_item
        ON pos_claims (item_id) WHERE status = 'ACTIVE';
    If two transactions both SELECT and see no ACTIVE claim (race between SELECT
    and INSERT), only one INSERT can succeed. The other raises IntegrityError,
    which the router translates to a 409. This index is declared with both
    `postgresql_where` and `sqlite_where` so E2E tests (SQLite) prove the
    DB-level constraint, not just the application-level check.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from yasargold_commerce.db import Base

_ACTIVE_WHERE = text("status = 'ACTIVE'")


class PosClaimRow(Base):
    __tablename__ = "pos_claims"

    id:         Mapped[str]      = mapped_column(String(40),  primary_key=True)
    item_id:    Mapped[int]      = mapped_column(Integer,     nullable=False, index=True)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status:     Mapped[str]      = mapped_column(String(20),  nullable=False, default="ACTIVE")

    __table_args__ = (
        # Fast lookup for all active-claim queries.
        Index("ix_pos_claims_item_active", "item_id", "status", "expires_at"),
        # Layer 2: partial unique index — at most one ACTIVE claim per item.
        # Works in SQLite 3.8.9+ (used in E2E tests) and PostgreSQL (production).
        Index(
            "ix_pos_claims_one_active_per_item",
            "item_id",
            unique=True,
            sqlite_where=_ACTIVE_WHERE,
            postgresql_where=_ACTIVE_WHERE,
        ),
    )
