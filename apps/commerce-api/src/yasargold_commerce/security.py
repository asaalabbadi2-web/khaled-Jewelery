"""Security classification registry for the Commerce API.

Every FastAPI route MUST have an entry in ROUTE_SECURITY before it can be
merged. The CI scan test (test_route_security_scan.py) walks app.routes and
fails if any APIRoute is missing from this registry.

Law 0: Every law has a test that proves it — otherwise it's a recommendation.
Law 1: Deny-by-default scope — every route declares its scope.
Law 3: Deny-by-default rate class — every route declares its rate_class.

To add a new endpoint:
    1. Add the entry to ROUTE_SECURITY here before writing the endpoint.
    2. Use a scope from VALID_SCOPES and a rate_class from VALID_RATE_CLASSES.
    3. If a new scope or rate_class is needed, add it to the frozenset and
       justify it in the note field.

Scopes:
    public     — no authentication required (read-only catalog, health)
    customer   — requires customer identity (JWT sub in v1.4)
    admin      — requires admin credential (currently: X-Admin-Secret)
    webhook    — called by external provider; signature-verified
    ops        — internal / monitoring endpoints

Rate classes (intent — enforcement deferred to v1.4):
    catalog-read       — cheap read, high volume allowed
    reservation-write  — expensive write, strict limit (prevents spam reservations)
    payment-write      — single-shot per session
    order-read         — customer self-service, moderate limit
    webhook            — low volume, provider-initiated
    admin-write        — internal ops, very low volume
    ops                — health/metrics, unlimited
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Route classification
# ---------------------------------------------------------------------------

VALID_SCOPES = frozenset({"public", "customer", "admin", "webhook", "ops"})

VALID_RATE_CLASSES = frozenset({
    "catalog-read",
    "reservation-write",
    "payment-write",
    "order-read",
    "webhook",
    "admin-write",
    "pos-write",
    "ops",
})


@dataclass(frozen=True)
class RouteSecurityClass:
    scope: str
    rate_class: str
    note: str = ""  # non-obvious constraints or temporary mitigations


# key = (HTTP_METHOD, path_template)   e.g. ("GET", "/api/v1/catalog/products")
ROUTE_SECURITY: dict[tuple[str, str], RouteSecurityClass] = {
    # ------------------------------------------------------------------
    # Catalog — public read-only
    # ------------------------------------------------------------------
    ("GET", "/api/v1/catalog/products"): RouteSecurityClass(
        scope="public", rate_class="catalog-read",
    ),
    ("GET", "/api/v1/catalog/items/{item_id}/availability"): RouteSecurityClass(
        scope="public", rate_class="catalog-read",
        note="INV-11: also consumed by POS UI (Gate B)",
    ),
    ("GET", "/api/v1/catalog/products/{slug}"): RouteSecurityClass(
        scope="public", rate_class="catalog-read",
    ),

    # ------------------------------------------------------------------
    # Reservations — customer write
    # ------------------------------------------------------------------
    ("POST", "/api/v1/reservations"): RouteSecurityClass(
        scope="customer", rate_class="reservation-write",
        note="v1.4: JWT required (get_customer_ref); customer_ref=JWT sub stored on Reservation",
    ),

    # ------------------------------------------------------------------
    # Payments — customer write + provider webhook
    # ------------------------------------------------------------------
    ("POST", "/api/v1/payments"): RouteSecurityClass(
        scope="customer", rate_class="payment-write",
        note="v1.4: JWT required; BOLA via res_row.customer_phone == customer_ref → 404 on mismatch",
    ),
    ("POST", "/api/v1/webhooks/payment"): RouteSecurityClass(
        scope="webhook", rate_class="webhook",
        note="Law 6: MoyasarSignatureError → 400 before any domain call",
    ),

    # ------------------------------------------------------------------
    # Orders — customer read
    # ------------------------------------------------------------------
    ("GET", "/api/v1/orders/{order_id}"): RouteSecurityClass(
        scope="customer", rate_class="order-read",
        note="v1.4: JWT required; BOLA via OrderService.find_order_for_customer(customer_ref)",
    ),
    ("GET", "/api/v1/reservations/{reservation_id}/order"): RouteSecurityClass(
        scope="customer", rate_class="order-read",
        note="v1.4: JWT required; BOLA via order.customer_ref == JWT sub",
    ),

    # ------------------------------------------------------------------
    # Shipments — mixed (GET=customer-read, mutating=admin)
    # ------------------------------------------------------------------
    ("POST", "/api/v1/orders/{order_id}/shipments"): RouteSecurityClass(
        scope="admin", rate_class="admin-write",
        note="v1.4: JWT required with scope=admin (require_admin); SEC-001 closed",
    ),
    ("GET", "/api/v1/orders/{order_id}/shipments"): RouteSecurityClass(
        scope="customer", rate_class="order-read",
        note="Sprint 10: BOLA closed — ownership via OrderService.find_order_for_customer(); identical 404 for non-owner and not-found",
    ),
    ("POST", "/api/v1/shipments/{shipment_id}/void"): RouteSecurityClass(
        scope="admin", rate_class="admin-write",
        note="v1.4: JWT required with scope=admin (require_admin); SEC-001 closed",
    ),
    ("POST", "/api/v1/shipments/{shipment_id}/deliver"): RouteSecurityClass(
        scope="admin", rate_class="admin-write",
        note="v1.4: JWT required with scope=admin (require_admin); SEC-001 closed",
    ),

    # ------------------------------------------------------------------
    # POS Claims — machine-to-machine ERP → Commerce (ADR-016 §H1 terminal fix)
    # ------------------------------------------------------------------
    ("POST", "/api/v1/items/{item_id}/pos-claim"): RouteSecurityClass(
        scope="admin", rate_class="pos-write",
        note="Auth: X-POS-Secret header (require_pos_auth); scope=admin because this is "
             "an ERP-to-Commerce internal write, not a customer-facing endpoint.",
    ),
    ("POST", "/api/v1/items/{item_id}/pos-claim/{claim_id}/confirm"): RouteSecurityClass(
        scope="admin", rate_class="pos-write",
        note="Auth: X-POS-Secret header (require_pos_auth); ERP calls after invoice commit.",
    ),
    ("DELETE", "/api/v1/items/{item_id}/pos-claim/{claim_id}"): RouteSecurityClass(
        scope="admin", rate_class="pos-write",
        note="Auth: X-POS-Secret header (require_pos_auth); ERP calls on invoice rollback.",
    ),

    # ------------------------------------------------------------------
    # Internal — ERP → Commerce machine-to-machine
    # ------------------------------------------------------------------
    ("POST", "/api/internal/gold-price"): RouteSecurityClass(
        scope="admin", rate_class="ops",
        note="Auth: X-Internal-Secret (require_internal_auth); ERP scheduler pushes "
             "fresh gold price after saving to its own DB. Rate=ops (unlimited) because "
             "volume is bounded by the ERP scheduler frequency (~1/min).",
    ),

    # ------------------------------------------------------------------
    # Ops
    # ------------------------------------------------------------------
    ("GET", "/health"): RouteSecurityClass(
        scope="public", rate_class="ops",
    ),
}

# ---------------------------------------------------------------------------
# Law 2 — Secrets never appear in logs
# ---------------------------------------------------------------------------

# Header names and payload keys whose VALUES must never reach log output.
# The RedactingFilter replaces any match with "<redacted>".
SENSITIVE_FIELD_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"authorization", re.IGNORECASE),
    re.compile(r"x-admin-secret", re.IGNORECASE),
    re.compile(r"x-internal-secret", re.IGNORECASE),
    re.compile(r"x-pos-secret", re.IGNORECASE),
    re.compile(r"x-moyasar-signature", re.IGNORECASE),
    re.compile(r"api[_\-]?key", re.IGNORECASE),
    re.compile(r"secret[_\-]?key", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
)

_REDACT_VALUE_RE = re.compile(
    r"("
    + "|".join(p.pattern for p in SENSITIVE_FIELD_PATTERNS)
    # Capture value: lazy match until next key=value, structural boundary, or EOL.
    # This handles both single-word values (api_key=sk_xyz) and multi-word values
    # like "Bearer TOKEN" in Authorization headers.
    + r")\s*[:=]\s*['\"]?(.+?)(?=\s+\w[\w_-]*\s*[:=]|[,}\]\"']|\s*$)",
    re.IGNORECASE | re.MULTILINE,
)


class RedactingFilter(logging.Filter):
    """Logging filter that replaces sensitive field values with <redacted>.

    Install on any logger or handler that may receive request context:
        handler.addFilter(RedactingFilter())

    Three surfaces redacted:

    1. `record.msg` — the format string or literal message.
    2. `record.args` — values interpolated into %s / %(name)s format strings.
       Secrets leak here when code does log.error("header: %s", auth_header).
    3. `record.exc_text` / `record.exc_info` — traceback strings.
       Secrets leak here when exception messages embed request context:
       raise ValueError(f"ERP rejected order {order_id} with token {token}")

    What this filter does NOT protect against:
    - Secrets passed as positional args to structured loggers (structlog, etc.)
      that do their own serialisation before calling the stdlib logger.
    - Secrets embedded in non-string extra fields (complex objects).
    For those, keep secrets out of log calls by construction — this filter
    is defence-in-depth, not a substitute for discipline.
    """

    @staticmethod
    def _redact(s: str) -> str:
        return _REDACT_VALUE_RE.sub(r"\1=<redacted>", s)

    def filter(self, record: logging.LogRecord) -> bool:
        # 1. Redact msg string
        if isinstance(record.msg, str):
            record.msg = self._redact(record.msg)

        # 2. Redact args (for "msg %s" % (secret,) style logging)
        if isinstance(record.args, tuple):
            record.args = tuple(
                self._redact(arg) if isinstance(arg, str) else arg
                for arg in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                k: self._redact(v) if isinstance(v, str) else v
                for k, v in record.args.items()
            }

        # 3. Redact tracebacks — format exc_info to text, redact, freeze as exc_text
        #    so that Formatter uses our pre-redacted version instead of re-formatting.
        if record.exc_info and record.exc_info[1] is not None:
            import traceback as _tb
            raw_tb = "".join(_tb.format_exception(*record.exc_info))
            redacted_tb = self._redact(raw_tb)
            if redacted_tb != raw_tb:
                record.exc_text = redacted_tb
                record.exc_info = None  # prevent Formatter from re-formatting

        return True
