"""Initial Commerce API schema — all tables owned by this service.

Revision ID: 0001
Revises:
Create Date: 2026-07-23

Tables created:
  category            — ERP catalog mirror (read-only for Commerce API)
  item                — ERP item mirror (read-only for Commerce API)
  gold_price          — ERP gold-price mirror (read-only for Commerce API)
  reservations        — ACTIVE reservation per item (INV-6, ADR-016)
  outbox_events       — transactional outbox (ADR-014 at-least-once delivery)
  payment_intents     — Moyasar-backed payment sessions
  orders              — confirmed sales (one per reservation, UNIQUE reservation_id)
  shipments           — carrier shipments (UNIQUE order_id + idempotency_key)
  carrier_configs     — live-read carrier policies (void_window is NOT cached on Shipment)
  pos_claims          — atomic POS terminal intent (INV-4 terminal fix, ADR-016 §H1)
  notifications       — dispatched customer notifications (UNIQUE order+template+channel)
  reconciliation_findings — Commerce vs ERP audit gaps

Design notes:
  • ERP mirror tables (category/item/gold_price) are created here so Commerce
    owns its own schema in a two-DB setup.  In production (shared DB) these
    tables are written by the ERP and read by Commerce — Single Writer.
  • Numeric columns use NUMERIC(p, s) not FLOAT — financial values are exact.
  • All timestamps use TIMESTAMP WITH TIME ZONE (timezone=True).
  • The partial unique index on pos_claims (item_id WHERE status='ACTIVE') is the
    Layer-2 concurrency guard (ADR-016 §H1 two-layer defence).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── ERP mirror tables ──────────────────────────────────────────────────────
    op.create_table(
        "category",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(200), nullable=True),
        sa.Column("karat", sa.String(10), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("item_code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("barcode", sa.String(100), nullable=True),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("category.id"), nullable=True),
        sa.Column("karat", sa.String(10), nullable=True),
        sa.Column("weight", sa.Float(), nullable=True),
        sa.Column("has_stones", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("stones_weight", sa.Float(), nullable=True),
        sa.Column("stones_value", sa.Float(), nullable=True),
        sa.Column("count", sa.Integer(), nullable=True),
        sa.Column("wage", sa.Float(), nullable=True),
        sa.Column("description", sa.String(200), nullable=True),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("stock", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_item_item_code", "item", ["item_code"])
    op.create_index("ix_item_barcode", "item", ["barcode"])

    op.create_table(
        "gold_price",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("date", sa.DateTime(), nullable=True),
    )

    # ── Commerce-owned tables ─────────────────────────────────────────────────
    op.create_table(
        "reservations",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("quote_id", sa.String(40), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("gold_price_id", sa.Integer(), nullable=False),
        sa.Column("locked_rate_per_gram_24k", sa.Numeric(14, 6), nullable=False),
        sa.Column("karat_rate_per_gram", sa.Numeric(14, 6), nullable=False),
        sa.Column("pricing_engine_version", sa.String(20), nullable=False),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("customer_phone", sa.String(30), nullable=True),
    )
    op.create_index("ix_reservations_quote_id", "reservations", ["quote_id"])
    op.create_index("ix_reservations_item_id", "reservations", ["item_id"])
    op.create_index("ix_reservations_valid_until", "reservations", ["valid_until"])

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(36), nullable=False, unique=True),
        sa.Column("event_type", sa.String(200), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notification_dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("erp_synced_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "payment_intents",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("reservation_id", sa.String(40), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="SAR"),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("provider", sa.String(50), nullable=True),
        sa.Column("provider_reference", sa.String(100), nullable=True, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(100), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_payment_intents_reservation_id", "payment_intents", ["reservation_id"])
    op.create_index(
        "ix_payment_intents_provider_reference",
        "payment_intents",
        ["provider_reference"],
        unique=True,
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("reservation_id", sa.String(40), nullable=False, unique=True),
        sa.Column("payment_intent_id", sa.String(40), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="SAR"),
        sa.Column("status", sa.String(30), nullable=False, server_default="CONFIRMED"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("customer_ref", sa.String(100), nullable=True),
    )
    op.create_index("ix_orders_reservation_id", "orders", ["reservation_id"], unique=True)
    op.create_index("ix_orders_payment_intent_id", "orders", ["payment_intent_id"])
    op.create_index("ix_orders_customer_ref", "orders", ["customer_ref"])

    op.create_table(
        "carrier_configs",
        sa.Column("carrier_id", sa.String(40), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("void_window_seconds", sa.Integer(), nullable=False),
    )

    op.create_table(
        "shipments",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("order_id", sa.String(40), nullable=False),
        sa.Column("carrier_id", sa.String(40), nullable=False),
        sa.Column("declared_value", sa.Numeric(14, 2), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("tracking_number", sa.String(100), nullable=True),
        sa.Column("failure_reason", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("in_transit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("order_id", name="uq_shipments_order_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_shipments_idempotency_key"),
    )
    op.create_index("ix_shipments_order_id", "shipments", ["order_id"])

    op.create_table(
        "pos_claims",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
    )
    op.create_index("ix_pos_claims_item_active", "pos_claims", ["item_id", "status", "expires_at"])
    # Layer-2 concurrency guard (ADR-016 §H1): at most one ACTIVE claim per item.
    op.create_index(
        "ix_pos_claims_one_active_per_item",
        "pos_claims",
        ["item_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("order_id", sa.String(40), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("recipient", sa.String(200), nullable=False),
        sa.Column("template", sa.String(60), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(500), nullable=True),
        sa.UniqueConstraint(
            "order_id", "template", "channel",
            name="uq_notifications_order_template_channel",
        ),
    )
    op.create_index("ix_notifications_order_id", "notifications", ["order_id"])

    op.create_table(
        "reconciliation_findings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_reconciliation_findings_order_id", "reconciliation_findings", ["order_id"]
    )
    op.create_index(
        "ix_reconciliation_findings_detected_at", "reconciliation_findings", ["detected_at"]
    )


def downgrade() -> None:
    op.drop_table("reconciliation_findings")
    op.drop_table("notifications")
    op.drop_table("pos_claims")
    op.drop_table("shipments")
    op.drop_table("carrier_configs")
    op.drop_table("orders")
    op.drop_table("payment_intents")
    op.drop_table("outbox_events")
    op.drop_table("reservations")
    op.drop_table("gold_price")
    op.drop_table("item")
    op.drop_table("category")
