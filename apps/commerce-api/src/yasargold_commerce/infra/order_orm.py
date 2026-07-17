"""SQLAlchemy ORM model for the orders write side.

orders — one row per confirmed sale. Created atomically with
         Reservation transitioning to COMPLETED (CheckoutUnitOfWork).

reservation_id has a UNIQUE constraint — one Order per Reservation.
item_id is NOT unique here (historical record; the item is already SOLD
when the Order exists, enforced by ERP consumer of OrderCreated event).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from yasargold_commerce.db import Base


class OrderRow(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    reservation_id: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    payment_intent_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    item_id: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[str] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="SAR")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="CONFIRMED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Populated from Reservation.customer_phone at creation (v1.4+). Used for BOLA.
    # Null on pre-v1.4 orders — those rows are dev/test records and cannot be read
    # via the customer-authenticated endpoint.
    customer_ref: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
