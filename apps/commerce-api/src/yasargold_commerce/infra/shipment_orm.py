"""SQLAlchemy ORM models for the shipping write side.

Tables:
  shipments       — one row per Order (UniqueConstraint on order_id)
  carrier_configs — carrier policies; void_window is live-read at decision time
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from yasargold_commerce.db import Base


class ShipmentRow(Base):
    __tablename__ = "shipments"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_shipments_order_id"),
        UniqueConstraint("idempotency_key", name="uq_shipments_idempotency_key"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    carrier_id: Mapped[str] = mapped_column(String(40), nullable=False)
    declared_value: Mapped[str] = mapped_column(Numeric(14, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    tracking_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    in_transit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CarrierConfigRow(Base):
    __tablename__ = "carrier_configs"

    carrier_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    void_window_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
