# ADR-017 — Security Architecture: Seven Laws

**Status:** Accepted
**Date:** 2026-07-14
**Sprint:** 9 — Security Architecture

---

## Context

At v1.3.1 the platform has:
- No authentication layer on the Commerce API (SEC-001)
- Admin endpoints protected only by a static `X-Admin-Secret` header (temporary mitigation)
- No rate limiting
- Two verified security invariants already holding: webhook signature before domain call (Law 6), secrets excluded from domain packages (Law 2 face 1)

Before v1.4 (first public-facing endpoint), this ADR freezes seven security laws. Each law has an **executable proof test** — by Law 0, a rule without a test is a recommendation.

The laws are ordered by blast radius.

**Terminology** — two enforcement dimensions are used throughout:
- **CI Enforcement:** verified at build/test time; catches structural violations before merge; does not affect individual HTTP requests.
- **Runtime Enforcement:** applied to every request while the system is running (e.g. JWT scope check, HMAC verification, log redaction filter).

See `architecture-v1.md §5.0` for the canonical definitions.

---

## Law 0 — The Meta-Law

> **Every law has a test that proves it. Otherwise it is a recommendation.**

Written first because it changes how the others are read. A law without a test is an aspiration. These laws are binding because their tests run in CI.

---

## Law 1 — Deny-by-Default Scope

Every FastAPI route must declare its security scope in `security.ROUTE_SECURITY` **before it is merged**. A route without a scope entry fails CI.

**Scopes:**

| Scope | Meaning | v1.3 enforcement | v1.4 enforcement |
|-------|---------|-----------------|-----------------|
| `public` | No auth required | Unrestricted | Unrestricted |
| `customer` | Requires verified customer identity | Unauthenticated (SEC-001) | JWT middleware |
| `admin` | Requires admin credential | `X-Admin-Secret` | RBAC role claim |
| `webhook` | Provider-initiated; signature-verified | Law 6 | Law 6 |
| `ops` | Internal monitoring | Unrestricted | IP-restricted |

**Proof test:** `tests/security/test_route_security_scan.py::TestLaw1DenyByDefaultScope`

The scan walks `app.router.routes` (including `_IncludedRouter` entries) and fails if any `APIRoute` is absent from the registry. Every new endpoint must be registered first — if it isn't, the first test run fails.

**Why:** How systems get compromised — the forgotten addition, not the intentional one.

---

## Law 2 — Secrets Never Pass Through Domain

Two faces:

**Face 1 (existing):** `import-linter` blocks `os.environ` and `settings` imports inside `packages/domain`. Domain code cannot read secrets — only infrastructure can inject them through Protocols.

**Face 2 (new):** `RedactingFilter` rewrites log records before they reach any handler. Sensitive field values (`Authorization`, `X-Admin-Secret`, `X-Internal-Secret`, `api_key`, `token`, etc.) are replaced with `<redacted>`.

**Proof test:** `tests/security/test_log_redaction.py`

**Installation:** Add `handler.addFilter(RedactingFilter())` to any handler that receives request context. The filter is defined in `yasargold_commerce.security`.

**Why:** Log aggregation pipelines (Datadog, CloudWatch, ELK) store logs for months. A token that appears in an error log becomes a credential that outlasts its intended lifetime.

---

## Law 3 — Deny-by-Default Rate Class

Every FastAPI route must declare its `rate_class` in `security.ROUTE_SECURITY`. A route without a rate class is unthrottled by construction — that is a security default, not a UX choice.

**Rate classes (intent):**

| Class | Examples | Enforcement in v1.4 |
|-------|----------|---------------------|
| `catalog-read` | GET /catalog/products | High limit (e.g. 100 req/min) |
| `reservation-write` | POST /reservations | Strict limit (e.g. 5 req/min) |
| `payment-write` | POST /payments | Single-shot per session |
| `order-read` | GET /orders/{id} | Moderate limit |
| `webhook` | POST /webhooks/payment | Provider IP allowlist |
| `admin-write` | POST /shipments/{id}/void | Very low limit + IP filter |
| `ops` | GET /health | Unlimited |

**Proof test:** `tests/security/test_route_security_scan.py::TestLaw3DenyByDefaultRateClass`

**v1.4 status:** `RateLimitMiddleware` in `yasargold_commerce.rate_limiter` is live. Fixed-window counter (Redis INCR + EXPIRE). Limits: `reservation-write` 5/min, `payment-write` 3/5min, `catalog-read` 200/min, `ops` unlimited. Client identity: `TRUSTED_PROXY_HOPS` (default 1) — `ips[-N]` from X-Forwarded-For (forge-resistant: client-supplied prefix ignored, LB-appended real IP used). In tests: `FakeRedis` (in-memory, reset via autouse fixture). In production: real `redis.Redis` when `REDIS_URL` is set; missing `REDIS_URL` with `COMMERCE_ENV=production` prevents app startup (`_check_production_redis_config()` in lifespan). Webhook rate class (`webhook`, 100/min) is independent of `payment-write` (3/5min) — Moyasar retries cannot be blocked by the payment counter. CGNAT caveat documented in `rate_limiter.py`: per-IP may need upgrading to IP+session in v1.5.

---

## Law 4 — RBAC on Capability

Permissions are granted on **capabilities**, not on routes. The RBAC check answers: "Does this role have permission to exercise this capability?" — not "does this role have permission to call this URL?"

**Roles (v1.4):**

| Role | Capabilities |
|------|-------------|
| `customer` | Create reservation, create payment, view own orders, view own shipments |
| `admin` | All customer capabilities + shipment lifecycle management |
| `webhook_provider` | Process payment webhooks |

**v1.4 status:** Both enforcement directions are live and proven:

- **Admin-side proof** — `tests/security/test_admin_scope_enforcement.py` (13 tests): customer JWT → 403 on all admin-scoped endpoints.
- **Customer-side proof** — `tests/security/test_law4_customer_scope.py` (16 tests): no JWT → 401 on all customer-scoped endpoints; valid customer JWT → passes auth; admin JWT → also passes (admin ⊇ customer). A structural scan verifies `_CUSTOMER_ENDPOINTS` in the test matches the count of `scope="customer"` entries in ROUTE_SECURITY — adding a new customer endpoint without adding it to the test breaks CI.

**Bug found and fixed (v1.4.6-dev):** `GET /api/v1/orders/{order_id}/shipments` was classified `scope="customer"` in ROUTE_SECURITY but had no `Depends(get_customer_ref)` in the route handler. The Law 4 proof test caught it. Fix: added `customer_ref: str = Depends(get_customer_ref)` to `get_shipment_by_order()` in `routers/shipments.py`.

**BOLA-shipments closed (Sprint 10):** `GET /api/v1/orders/{order_id}/shipments` now enforces ownership via `OrderService.find_order_for_customer()` before any shipment query. Non-owner and non-existent orders return identical 404 responses — no resource enumeration. Proof: `tests/security/test_shipment_bola.py` (4 tests). All open BOLA surfaces are now closed.

**SEC-001 withdrawal condition** remains:
1. Runtime scope enforcement live (✅ — JWT middleware enforces `get_customer_ref` and `require_admin` on all classified routes)
2. Test proves admin endpoints reject under-privileged JWTs (✅ — `test_admin_scope_enforcement.py`)
3. **Now also: test proves customer endpoints reject unauthenticated requests (✅ — `test_law4_customer_scope.py`)**

---

## Law 5 — BOLA: Ownership Check Lives in Domain Service

BOLA (Broken Object Level Authorization, OWASP #1) in commerce contexts: a customer changes an ID in the URL and reads or cancels another customer's order/reservation.

**The fix:**

```
✗ router:  if reservation.customer_phone != request.customer_phone: raise HTTPException(403)
✓ service: result = service.find_reservation_for_customer(id, customer_ref, uow)
           # router maps None → 404
```

**Rules:**
1. Ownership check lives in the domain service method, not in the router.
2. The service returns `None` when ownership fails — never raises.
3. The router maps `None` → 404 (not 403). Returning 403 confirms the resource exists — that is an oracle attack.
4. `customer_ref = None` (unauthenticated) always returns `None` — deny by default.

**Proof test:** `packages/domain/tests/reservation/test_bola.py`

**v1.3 implementation:** `ReservationService.find_reservation_for_customer()` uses `customer_phone` as `customer_ref` (weak, not verified). Pattern established.

**v1.4 implementation:** `customer_ref` = verified JWT `sub` claim injected by middleware before domain call.

**Closed BOLA surfaces (all surfaces now closed):**
- `POST /api/v1/payments` — fixed v1.4.3: ownership via `ReservationService.find_reservation_for_customer()`. Proof: `tests/security/test_payment_bola.py`.
- `GET /api/v1/orders/{order_id}` — `find_order_for_customer()` in `OrderService`. Proof: `tests/security/test_bola.py` (domain) + orders router.
- `GET /api/v1/orders/{order_id}/shipments` — fixed Sprint 10: ownership via `OrderService.find_order_for_customer()` before shipment query; identical 404 for all rejection cases (no enumeration). Proof: `tests/security/test_shipment_bola.py` (4 tests).

**No remaining open BOLA surfaces.** The open-surface witness file (`tests/security/test_open_surfaces.py`) is now empty of xfail tests.

§5 — Transitional implementation note:
`find_shipment_for_customer()` was not added to `ShipmentService` because `Shipment`
aggregates do not carry `customer_ref` — that field lives on `Order`. Introducing it
in `ShipmentService` would require cross-context access to `OrderRepository`, creating
bounded-context coupling. The ownership rule is composed at the router level using two
existing domain primitives. This is the accepted transitional form until ADR-023 M2.x
consolidates the shipping and order bounded contexts.

---

## Law 6 — No Domain Translation Before Signature Verification

The webhook handler must verify the provider signature **before** creating any domain object or calling any domain service.

**Invariant:** `MoyasarSignatureError` is raised inside `gateway.parse_webhook()` before `WebhookResult` is constructed. The router catches it and returns 400. The domain `PaymentService.confirm()` is never called.

**Proof test:** `apps/commerce-api/tests/security/test_webhook_signature.py::TestLaw6WebhookSignatureVerification::test_forged_payload_does_not_reach_domain_service`

This test proves the ordering at runtime: forged payload → spy records whether domain was called → assert `transition_called == False`.

**Extends:** ADR-010 (webhook translation layer).

---

## "What We Deliberately Do Not Do"

| We do not | Reason |
|-----------|--------|
| Issue long-lived API keys to customers | Short-lived JWTs with refresh tokens |
| Store JWT in localStorage | Cookie with `HttpOnly` + `SameSite=Strict` |
| Return 403 on resource ownership failure | 403 confirms resource existence (oracle). Return 404 |
| Allow CORS wildcard (`*`) in production | `ALLOWED_ORIGINS` env var must be set explicitly |
| Pass tokens through query parameters | Query params appear in access logs and browser history |
| Import `os.environ` inside `packages/domain` | Law 2 face 1; enforced by import-linter |

---

## Test Inventory

| Law | Test file | Count |
|-----|-----------|-------|
| Law 0 (meta) | Proven by Law 1+3 scan passing | — |
| Law 1 (scope scan) | `tests/security/test_route_security_scan.py` | 4 tests |
| Law 2 face 2 (redaction) | `tests/security/test_log_redaction.py` | 16 tests (msg · args · tracebacks) |
| Law 3 (rate class scan) | `tests/security/test_route_security_scan.py` | 4 tests |
| Law 3 (rate enforcement) | `tests/security/test_rate_limiting.py` | 30 tests (unit + middleware + XFF forge + webhook isolation + production config) |
| Law 4 (RBAC) admin-side | `tests/security/test_admin_scope_enforcement.py` | 13 tests |
| Law 4 (RBAC) customer-side | `tests/security/test_law4_customer_scope.py` | 16 tests |
| Law 5 (BOLA) reservations | `packages/domain/tests/reservation/test_bola.py` | 6 tests |
| Law 5 (BOLA) payments | `tests/security/test_payment_bola.py` | 4 tests |
| Law 6 (signature before translation) | `tests/security/test_webhook_signature.py` | 4 tests |

Total: 97 security tests.

---

## Consequences

### Positive

**Deny-by-default is structural, not per-request.** Laws 1 and 3 make "forgot to classify" a CI failure, not a production incident.

**BOLA ownership check is in the right layer.** The domain service decides ownership; the router translates to HTTP. Adding a new customer-facing endpoint in v1.4 follows the same pattern automatically.

**Webhook forgery is already proven impossible** at the code level. The existing implementation was correct; Law 6 makes that correctness observable.

### Watch Out For

**SEC-001 withdrawn (v1.4.6-dev).** `require_admin_secret` is now replaced by `require_admin` (JWT scope="admin") on all admin routes. All three withdrawal conditions are met:
1. Runtime scope enforcement live — `get_customer_ref` + `require_admin` Depends on all classified routes.
2. Admin endpoints reject under-privileged JWTs — `test_admin_scope_enforcement.py` (13 tests).
3. Customer endpoints reject unauthenticated requests — `test_law4_customer_scope.py` (16 tests).

**BOLA open on order read endpoints.** `GET /api/v1/orders/{order_id}` returns any order to any caller. Documented and accepted for v1.3; must be fixed before authenticated customer-facing traffic.

**Rate limiting not enforced.** Rate classes are declared; Redis-based enforcement is deferred to v1.4. Until then, `reservation-write` can be spammed.

---

## Related

- ADR-010 — Webhook translation layer (Law 6 extends)
- ADR-016 — ERP Sync; SEC-003 declared there
- `apps/commerce-api/src/yasargold_commerce/security.py` — ROUTE_SECURITY registry
- `§5` Security Laws in `architecture-v1.md`
