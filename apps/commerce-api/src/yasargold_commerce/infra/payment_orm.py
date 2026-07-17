"""SQLAlchemy ORM model for the payment_intents write table.

The Commerce API owns this table. It is not a mirror of any ERP table.

Schema notes:
  - provider_reference has a unique index: one intent per gateway session.
  - reservation_id is indexed: look up all intents for a reservation.
  - failure_reason is nullable: only set when status = FAILED.
  - paid_at is nullable: only set when status = PAID.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from yasargold_commerce.db import Base


class PaymentIntentRow(Base):
    __tablename__ = "payment_intents"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    reservation_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    amount: Mapped[str] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="SAR")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    provider_reference: Mapped[str | None] = mapped_column(
        String(100), nullable=True, unique=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
