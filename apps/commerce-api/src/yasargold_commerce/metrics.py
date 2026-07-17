"""Prometheus metrics for the Commerce API.

All metrics are module-level singletons (prometheus-client global registry).
Import and record at call sites — never create new metrics inside functions.

Naming convention:
  yasargold_<subsystem>_<metric>_<unit>
  (prefix dropped for brevity since we own the namespace)

Operational dashboard targets:
  - Reservation success / conflict rates → SLI for availability
  - Lock duration P95 → latency signal for DB contention
  - Outbox events pending → backlog alert (should stay near 0)
  - Expiry rate → healthy if matches reservation volume over time
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# Reservations
# ---------------------------------------------------------------------------

RESERVATION_SUCCESS = Counter(
    "reservation_success_total",
    "Reservations successfully created (HTTP 201)",
)

RESERVATION_CONFLICT = Counter(
    "reservation_conflict_total",
    "Reservation attempts rejected: item already reserved (HTTP 409)",
)

RESERVATION_POLICY_DENIED = Counter(
    "reservation_policy_denied_total",
    "Reservation attempts rejected by a CompositePolicy rule",
    labelnames=["reason"],
    # Labels: QUOTE_EXPIRED | QUOTE_STATUS_INVALID | TRADING_HALTED |
    #         ITEM_UNAVAILABLE | CUSTOMER_INELIGIBLE | DAILY_LIMIT_EXCEEDED
)

RESERVATION_EXPIRED = Counter(
    "reservation_expired_total",
    "Reservations transitioned to EXPIRED by the Expiry Worker",
)

RESERVATION_CONFIRMED = Counter(
    "reservation_confirmed_total",
    "Reservations confirmed via payment webhook",
)

RESERVATION_LOCK_DURATION = Histogram(
    "reservation_lock_duration_seconds",
    "Time spent in lock_item() (SELECT FOR UPDATE NOWAIT round-trip to PostgreSQL)",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5],
)

# ---------------------------------------------------------------------------
# Outbox
# ---------------------------------------------------------------------------

OUTBOX_EVENTS_PENDING = Gauge(
    "outbox_events_pending",
    "Number of outbox_events rows where published_at IS NULL",
)

OUTBOX_PUBLISH_DURATION = Histogram(
    "outbox_publish_duration_seconds",
    "Time to call publish_fn() for a single event",
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
)

OUTBOX_BATCH_SIZE = Histogram(
    "outbox_batch_size_events",
    "Events processed per Outbox Worker tick",
    buckets=[1, 5, 10, 25, 50, 100],
)

OUTBOX_WORKER_ERRORS = Counter(
    "outbox_worker_errors_total",
    "Outbox Worker ticks that failed (batch rolled back, will retry)",
)

# ---------------------------------------------------------------------------
# Quote & reservation lifecycle
# ---------------------------------------------------------------------------

QUOTE_AGE_SECONDS = Histogram(
    "quote_age_seconds",
    "Age of the gold price quote at the moment of successful reservation"
    " — use to tune the FRESH_TTL threshold",
    buckets=[5, 15, 30, 60, 90, 120, 180, 300],
)

RESERVATION_LIFETIME_SECONDS = Histogram(
    "reservation_lifetime_seconds",
    "Time from reservation creation to terminal state (confirmed / expired)",
    labelnames=["outcome"],  # "confirmed" | "expired"
    buckets=[60, 300, 600, 900, 1800, 3600, 7200],
)

# ---------------------------------------------------------------------------
# Expiry Worker
# ---------------------------------------------------------------------------

EXPIRY_WORKER_BATCH_SIZE = Histogram(
    "expiry_worker_batch_size_reservations",
    "Reservations expired per Expiry Worker tick",
    buckets=[0, 1, 5, 10, 25, 50, 100],
)

EXPIRY_WORKER_ERRORS = Counter(
    "expiry_worker_errors_total",
    "Expiry Worker ticks that failed (batch rolled back, will retry)",
)

# ---------------------------------------------------------------------------
# Payment
# ---------------------------------------------------------------------------

PAYMENT_INTENT_CREATED = Counter(
    "payment_intent_created_total",
    "PaymentIntents successfully created and gateway session opened (HTTP 201)",
)

PAYMENT_RECEIVED = Counter(
    "payment_received_total",
    "Webhook-confirmed successful payments (intent → PAID)",
)

PAYMENT_FAILED = Counter(
    "payment_failed_total",
    "Webhook-reported payment failures (intent → FAILED)",
    labelnames=["failure_reason"],
    # Labels: card_declined | insufficient_funds | expired_card | unknown | …
)

PAYMENT_WEBHOOK_LATENCY = Histogram(
    "payment_webhook_latency_seconds",
    "Time from webhook receipt to uow.commit() completing"
    " — includes PaymentService.confirm() + CheckoutService.confirm()",
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

PAYMENT_GATEWAY_REQUEST_DURATION = Histogram(
    "payment_gateway_request_duration_seconds",
    "Time spent in PaymentGateway.initiate() — round-trip to payment provider",
    labelnames=["provider"],  # "moyasar" | "tap" | …
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0],
)

PAYMENT_GATEWAY_FAILURES = Counter(
    "payment_gateway_failures_total",
    "HTTP errors and network failures calling the payment provider",
    labelnames=["provider", "error_type"],
    # error_type: "http_4xx" | "http_5xx" | "timeout" | "network"
)

# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

ORDER_CREATED = Counter(
    "order_created_total",
    "Orders successfully created from confirmed payments (CONFIRMED status)",
)

ORDER_CANCELLED = Counter(
    "order_cancelled_total",
    "Orders cancelled before delivery",
    labelnames=["reason"],
)

# ---------------------------------------------------------------------------
# ERP Sync (Sprint 8)
# ---------------------------------------------------------------------------

ERP_SYNC_SUCCESS = Counter(
    "erp_sync_success_total",
    "OrderCreated events successfully synced to ERP",
)

ERP_SYNC_ERRORS = Counter(
    "erp_sync_errors_total",
    "OrderCreated events that failed to sync to ERP (will retry)",
)

ERP_SYNC_LAG_SECONDS = Histogram(
    "erp_sync_lag_seconds",
    "Time between OrderCreated event creation and successful ERP sync. "
    "SLO: P95 ≤ 30s. Alert if P95 > 30s — indicates ERPSyncWorker is behind "
    "and the INV-4 compensation window is growing.",
    buckets=[1, 5, 10, 30, 60, 120, 300, 600],
)

# ---------------------------------------------------------------------------
# Refund Worker (Sprint 8)
# ---------------------------------------------------------------------------

REFUND_SUCCESS = Counter(
    "refund_success_total",
    "PaymentIntents successfully transitioned REFUND_PENDING → REFUNDED",
)

REFUND_PERMANENT_FAILURES = Counter(
    "refund_permanent_failures_total",
    "Refunds rejected permanently by gateway — manual action required",
)

REFUND_TRANSIENT_FAILURES = Counter(
    "refund_transient_failures_total",
    "Transient refund gateway failures — will retry next tick",
)

# ---------------------------------------------------------------------------
# Refund Gateway (Sprint 11 — adapter-level; worker-level metrics above)
# ---------------------------------------------------------------------------

PAYMENT_REFUND_SUCCESS = Counter(
    "payment_refund_success_total",
    "Moyasar refund HTTP calls that returned 200 (adapter layer)",
)

PAYMENT_REFUND_FAILURE = Counter(
    "payment_refund_failure_total",
    "Moyasar refund HTTP calls that ended in an error (adapter layer)",
    labelnames=["kind"],
    # kind: "transient" | "permanent"
)

PAYMENT_REFUND_DURATION = Histogram(
    "payment_refund_duration_seconds",
    "Total wall-clock time for MoyasarRefundGateway.refund() — includes retries",
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

# ---------------------------------------------------------------------------
# SMS Dispatch — TwilioNotificationGateway (Sprint 11 — adapter layer)
# ---------------------------------------------------------------------------

SMS_DISPATCH_SUCCESS = Counter(
    "sms_dispatch_success_total",
    "Twilio SMS API calls that returned 201 (adapter layer)",
)

SMS_DISPATCH_FAILURE = Counter(
    "sms_dispatch_failure_total",
    "Twilio SMS API calls that ended in an error (adapter layer)",
    labelnames=["kind"],
    # kind: "transient" (5xx/network/timeout) | "permanent" (4xx)
)

SMS_DISPATCH_DURATION = Histogram(
    "sms_dispatch_duration_seconds",
    "Wall-clock time for TwilioNotificationGateway.send() — no retries (retry budget = 0)",
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
)

# ---------------------------------------------------------------------------
# Carrier Shipment — AramexCarrierGateway (Sprint 11 — adapter layer)
# ---------------------------------------------------------------------------

CARRIER_SHIPMENT_SUCCESS = Counter(
    "carrier_shipment_success_total",
    "Carrier create_shipment calls that returned a tracking number (adapter layer)",
)

CARRIER_SHIPMENT_FAILURE = Counter(
    "carrier_shipment_failure_total",
    "Carrier create_shipment calls that ended in an error (adapter layer)",
    labelnames=["kind"],
    # kind: "transient" (5xx/network/timeout exhaustion) | "permanent" (4xx)
)

CARRIER_SHIPMENT_DURATION = Histogram(
    "carrier_shipment_duration_seconds",
    "Wall-clock time for AramexCarrierGateway.create_shipment() — includes retries",
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

CARRIER_VOID_SUCCESS = Counter(
    "carrier_void_success_total",
    "Carrier void_shipment calls that succeeded (adapter layer)",
)

CARRIER_VOID_FAILURE = Counter(
    "carrier_void_failure_total",
    "Carrier void_shipment calls that ended in an error (adapter layer)",
    labelnames=["kind"],
    # kind: "transient" | "permanent"
)

CARRIER_VOID_DURATION = Histogram(
    "carrier_void_duration_seconds",
    "Wall-clock time for AramexCarrierGateway.void_shipment() — includes retries",
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0],
)

# ---------------------------------------------------------------------------
# Reconciliation (Sprint 8)
# ---------------------------------------------------------------------------

RECONCILIATION_GAPS = Counter(
    "reconciliation_gaps_total",
    "Commerce orders with no matching ERP invoice or amount mismatch. "
    "Alert threshold: ANY value > 0 — every gap is an open incident.",
    labelnames=["kind"],
    # kind: "MISSING_ERP_INVOICE" | "AMOUNT_MISMATCH"
)

RECONCILIATION_ORDERS_CHECKED = Counter(
    "reconciliation_orders_checked_total",
    "Total PAID Commerce orders checked in each reconciliation pass",
)
