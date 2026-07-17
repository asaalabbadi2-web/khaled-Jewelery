"""Read-only SQLAlchemy models mapping to existing ERP tables.

These are thin mirrors — only the columns the Commerce API needs to read.
No writes happen here; all mutations go through the ERP service layer.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from yasargold_commerce.db import Base


class Category(Base):
    __tablename__ = "category"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(200))
    karat: Mapped[str | None] = mapped_column(String(10))
    created_at: Mapped[datetime | None] = mapped_column(DateTime)

    items: Mapped[list["Item"]] = relationship("Item", back_populates="category")


class Item(Base):
    __tablename__ = "item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    barcode: Mapped[str | None] = mapped_column(String(100), index=True)
    category_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("category.id"))
    karat: Mapped[str | None] = mapped_column(String(10))
    weight: Mapped[float | None] = mapped_column(Float)
    has_stones: Mapped[bool] = mapped_column(Boolean, default=False)
    stones_weight: Mapped[float | None] = mapped_column(Float)
    stones_value: Mapped[float | None] = mapped_column(Float)
    count: Mapped[int | None] = mapped_column(Integer)
    wage: Mapped[float | None] = mapped_column(Float)
    description: Mapped[str | None] = mapped_column(String(200))
    price: Mapped[float] = mapped_column(Float, nullable=False)
    stock: Mapped[int] = mapped_column(Integer, default=0)

    category: Mapped["Category | None"] = relationship("Category", back_populates="items")


class GoldPrice(Base):
    __tablename__ = "gold_price"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    date: Mapped[datetime | None] = mapped_column(DateTime)
