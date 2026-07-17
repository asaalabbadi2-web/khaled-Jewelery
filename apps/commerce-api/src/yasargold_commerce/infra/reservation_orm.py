"""SQLAlchemy ORM models for the reservation write side.

These are WRITE models — the Commerce API owns these tables.
They are not mirrors of ERP tables.

Tables:
  reservations   — one row per confirmed reservation
  outbox_events  — transactional outbox (Worker reads and publishes events)
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from yasargold_commerce.db import Base


class ReservationRow(Base):
    __tablename__ = "reservations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    quote_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    item_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    gold_price_id: Mapped[int] = mapped_column(Integer, nullable=False)
    locked_rate_per_gram_24k: Mapped[str] = mapped_column(Numeric(14, 6), nullable=False)
    karat_rate_per_gram: Mapped[str] = mapped_column(Numeric(14, 6), nullable=False)
    pricing_engine_version: Mapped[str] = mapped_column(String(20), nullable=False)
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    customer_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)


class OutboxEventRow(Base):
    __tablename__ = "outbox_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    event_type: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notification_dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    erp_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
