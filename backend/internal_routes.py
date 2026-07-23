"""ERP Sync internal API — machine-to-machine only.

This blueprint serves the Commerce API's ERPSyncWorker. It is NOT exposed to
end-users or the POS frontend. The only caller is the Commerce API worker
running in the same internal network.

Endpoint:
    POST /api/internal/online-orders

    Receives an OrderCreated payload from the Commerce API outbox worker.
    For each new order:
        1. Finds the Item by item_id.
        2. Decrements Item.stock by 1.
        3. Creates an Invoice (invoice_type='بيع', status='paid') linking
           commerce_order_id for idempotency.
        4. Creates an InvoiceItem row.
        5. Commits in one transaction.

    Idempotency: if an Invoice with that commerce_order_id already exists,
    returns 200 {"status": "already_processed"} without creating duplicates.

Authentication:
    X-Internal-Secret header must match ERP_INTERNAL_SECRET env var.
    If env var is unset → 503 (internal API unconfigured).
    If header is wrong  → 403.

    This is a lightweight secret-based guard for internal service-to-service
    calls on the same private network. It will be replaced by mTLS or a proper
    service mesh token when the infrastructure is hardened.
"""
from __future__ import annotations

import os
import secrets
import logging
from datetime import datetime

from flask import Blueprint, jsonify, request

log = logging.getLogger(__name__)

internal_bp = Blueprint("internal", __name__, url_prefix="/api/internal")


def _check_internal_secret() -> tuple[bool, object | None]:
    """Returns (ok, error_response). Call before any business logic."""
    expected = os.environ.get("ERP_INTERNAL_SECRET")
    if not expected:
        return False, (jsonify({"error": "internal API not configured — set ERP_INTERNAL_SECRET"}), 503)
    provided = request.headers.get("X-Internal-Secret", "")
    # secrets.compare_digest prevents timing-based enumeration on the network boundary.
    if not secrets.compare_digest(provided, expected):
        return False, (jsonify({"error": "forbidden"}), 403)
    return True, None


@internal_bp.post("/online-orders")
def sync_online_order():
    """Sync a Commerce API OrderCreated event into ERP.

    Body (JSON):
        order_id   — Commerce order UUID
        item_id    — ERP integer item ID
        amount     — total amount (float, SAR)
        currency   — ISO 4217 (usually "SAR")

    Returns:
        201 {"status": "created", "invoice_id": <int>}
        200 {"status": "already_processed", "invoice_id": <int>}
        400 bad request
        404 item not found
        409 item out of stock
        503 / 403 auth errors
    """
    ok, err = _check_internal_secret()
    if not ok:
        return err

    body = request.get_json(silent=True) or {}
    order_id = body.get("order_id", "").strip()
    item_id = body.get("item_id")
    amount = body.get("amount")
    currency = body.get("currency", "SAR")

    if not order_id or item_id is None or amount is None:
        return jsonify({"error": "order_id, item_id, and amount are required"}), 400

    try:
        item_id = int(item_id)
        amount = float(amount)
    except (ValueError, TypeError):
        return jsonify({"error": "item_id must be int, amount must be numeric"}), 400

    # Import inside function to avoid circular imports at module load time.
    from models import db, Invoice, InvoiceItem, Item
    from routes import _next_invoice_type_id

    # Idempotency guard — one invoice per Commerce order.
    existing = Invoice.query.filter_by(commerce_order_id=order_id).first()
    if existing is not None:
        log.info("internal.sync_online_order: already_processed order=%s invoice=%s", order_id, existing.id)
        return jsonify({"status": "already_processed", "invoice_id": existing.id}), 200

    # Load item.
    item = Item.query.get(item_id)
    if item is None:
        log.warning("internal.sync_online_order: item %s not found for order %s", item_id, order_id)
        return jsonify({"error": f"item {item_id} not found"}), 404

    if item.stock is not None and item.stock <= 0:
        log.warning(
            "internal.sync_online_order: item %s out of stock (stock=%s) for order %s",
            item_id, item.stock, order_id,
        )
        return jsonify({"error": "item out of stock", "item_id": item_id}), 409

    try:
        now = datetime.utcnow()
        next_type_id = _next_invoice_type_id(["بيع"])

        invoice = Invoice(
            invoice_type="بيع",
            invoice_type_id=next_type_id,
            date=now,
            total=amount,
            status="paid",
            is_posted=False,
            commerce_order_id=order_id,
            # currency is stored via payment_method for now; total is SAR
        )
        db.session.add(invoice)
        db.session.flush()  # get invoice.id before creating InvoiceItem

        invoice_item = InvoiceItem(
            invoice_id=invoice.id,
            item_id=item.id,
            name=item.name,
            quantity=1,
            price=amount,
            karat=float(item.karat) if item.karat else None,
            weight=item.weight,
            wage=item.wage,
            net=amount,
            tax=0.0,
        )
        db.session.add(invoice_item)

        # Decrement stock (single-piece jewelry — always 1 unit per order).
        if item.stock is not None:
            item.stock = max(0, item.stock - 1)

        db.session.commit()

        log.info(
            "internal.sync_online_order: created invoice=%s for order=%s item=%s amount=%s",
            invoice.id, order_id, item_id, amount,
        )
        return jsonify({"status": "created", "invoice_id": invoice.id}), 201

    except Exception:
        db.session.rollback()
        log.exception("internal.sync_online_order: failed for order=%s", order_id)
        return jsonify({"error": "internal server error"}), 500


@internal_bp.get("/item-sale/<int:item_id>")
def check_item_sale(item_id: int):
    """Return the most recent committed POS sale for item_id after a given timestamp.

    Used by ReconciliationWorker (F1) to detect orphaned pos-claims: ACTIVE claims
    whose TTL expired without a CONFIRMED call, where the ERP nevertheless committed
    a sale. An orphaned claim means the item appears available online even though it
    was already sold at the counter.

    Query params:
        after  — ISO 8601 UTC timestamp; only sales created at or after this time

    Returns:
        200 {"invoice_id": <int>, "total": <float>}  — committed sale found
        404                                           — no sale after that time
        400 / 403 / 503                               — input / auth errors
    """
    ok, err = _check_internal_secret()
    if not ok:
        return err

    after_str = request.args.get("after", "").strip()
    if not after_str:
        return jsonify({"error": "after parameter required"}), 400

    try:
        # ERP stores naive datetimes; strip timezone offset after converting to UTC.
        after_dt = datetime.fromisoformat(after_str.replace("Z", "+00:00"))
        after_naive = after_dt.replace(tzinfo=None)
    except ValueError:
        return jsonify({"error": "after must be an ISO 8601 timestamp"}), 400

    from models import db, Invoice, InvoiceItem

    invoice = (
        db.session.query(Invoice)
        .join(InvoiceItem, InvoiceItem.invoice_id == Invoice.id)
        .filter(InvoiceItem.item_id == item_id)
        .filter(Invoice.invoice_type == "بيع")
        .filter(Invoice.created_at >= after_naive)
        .order_by(Invoice.created_at.asc())
        .first()
    )

    if invoice is None:
        return jsonify({"found": False}), 404

    return jsonify({
        "invoice_id": invoice.id,
        "total": invoice.total,
    }), 200


@internal_bp.get("/order-reconcile/<order_id>")
def order_reconcile(order_id: str):
    """Return ERP invoice data for a given Commerce order_id (reconciliation).

    Used by ReconciliationWorker to verify Commerce vs ERP totals.

    Returns:
        200 {"invoice_id": <int>, "total": <float>, "status": <str>}
        404 if no invoice exists for this commerce_order_id
        403 / 503 auth errors
    """
    ok, err = _check_internal_secret()
    if not ok:
        return err

    from models import Invoice
    invoice = Invoice.query.filter_by(commerce_order_id=order_id).first()
    if invoice is None:
        return jsonify({"error": "not found"}), 404

    return jsonify({
        "invoice_id": invoice.id,
        "total": invoice.total,
        "status": invoice.status,
    }), 200
