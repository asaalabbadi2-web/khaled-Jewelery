"""ORM table for reconciliation findings (Commerce vs ERP).

A reconciliation gap is either explained (resolved_at is set) or it is
an open incident. The row stays in this table permanently so the audit
trail is never lost.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from yasargold_commerce.db import Base


class ReconciliationFindingRow(Base):
    __tablename__ = "reconciliation_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(
        String(40), nullable=False
    )  # "MISSING_ERP_INVOICE" | "AMOUNT_MISMATCH"
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
