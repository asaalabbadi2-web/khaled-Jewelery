# ADR-018 — JWT Authentication Architecture

**Status:** Accepted
**Date:** 2026-07-14
**Sprint:** 10 — JWT Authentication Layer

---

## Context

At v1.3.x (post-Sprint 9), the platform had:
- All endpoints unauthenticated on the customer side (SEC-001)
- Admin endpoints protected by a static `X-Admin-Secret` header (`require_admin_secret`)
- Security laws 1, 4, and 5 declared but not yet runtime-enforced

ADR-017 §Consequences defined the SEC-001 withdrawal condition:
1. Runtime scope enforcement live on all `admin`-scoped routes
2. A test proves admin endpoints reject a valid JWT without the admin scope

This ADR describes the JWT architecture that satisfies both conditions and closes SEC-001.

---

## Decision

### Token Format

HS256-signed JWTs. Required claims:

| Claim | Type | Meaning |
|-------|------|---------|
| `sub` | string | Customer identity (phone number or customer ID) |
| `scope` | string | `"customer"` or `"admin"` |
| `exp` | NumericDate | Expiry; validated by PyJWT automatically |
| `iat` | NumericDate | Issued at; informational |

**Why HS256 over RS256:** v1.4 is a single-service deployment. Asymmetric signing (RS256) is justified when multiple services need to verify tokens independently. When we extract a separate auth service or add service-to-service JWTs, we will upgrade to RS256 at that point (a new ADR will govern the key rotation plan).

### Secret Configuration

`JWT_SECRET_KEY` environment variable. Minimum 32 bytes recommended (PyJWT warns below this threshold). Must never appear in logs — `X-Admin-Secret` is in `security.SENSITIVE_FIELD_PATTERNS`; `JWT_SECRET_KEY` is an env var that never enters request flow directly.

### FastAPI Dependencies (`auth.py`)

```
Bearer token
     │
     ▼
_get_claims() ── validates signature, expiry, required claims ──► TokenClaims(sub, scope)
     │
     ├──► get_customer_ref() ── returns claims.sub ──► customer_ref: str
     │       (used in customer-scoped endpoints + BOLA ownership checks)
     │
     └──► require_admin() ── checks scope == "admin" ──► None (or 403)
             (replaces require_admin_secret on all admin-scoped endpoints)
```

**Error responses:**
- No `Authorization` header → 401 with `WWW-Authenticate: Bearer`
- Invalid/expired token → 401
- Valid token, wrong scope → 403
- `JWT_SECRET_KEY` not set → 503 (configuration error)

### Scope Enforcement

| Scope | v1.4 enforcement |
|-------|-----------------|
| `public` | No auth required |
| `customer` | `get_customer_ref()` — valid JWT, any scope with `sub` |
| `admin` | `require_admin()` — valid JWT with `scope=admin` |
| `webhook` | Law 6 (HMAC signature) — no JWT |
| `ops` | No auth (health/metrics) |

### BOLA Ownership (Law 5 — Runtime)

`customer_ref` (from JWT `sub`) is passed to domain service methods for ownership verification:

```python
# GET /api/v1/orders/{order_id}
order = order_service.find_order_for_customer(OrderId(order_id), customer_ref, uow)
if order is None:
    raise HTTPException(404)  # not 403 — 403 is an oracle attack
```

`OrderService.find_order_for_customer()` returns `None` when:
- `customer_ref` is `None` (unauthenticated)
- Order does not exist
- `order.customer_ref != customer_ref` (BOLA)
- `order.customer_ref` is `None` (pre-v1.4 record without ownership data)

### customer_ref on Order

`customer_ref: str | None` is stored on the `Order` aggregate and `OrderRow`. Populated from `Reservation.customer_phone` at checkout (`CheckoutService.confirm()` threads it through `OrderService.create_from_reservation()`). Pre-v1.4 orders have `customer_ref=NULL` and are inaccessible via the authenticated endpoint.

### customer_ref as a Stable Principal Identifier

`customer_ref` is intentionally opaque to the domain. The domain does not know — and must not assume — whether the value is a phone number, a UUID, an email address, or an internal customer ID.

**The domain only knows:** "this resource belongs to whoever presented this string."

**The auth layer knows:** how to map an authenticated request to that string.

```
Auth provider (JWT, OAuth, OIDC, Keycloak, Auth0)
     │
     │  extracts JWT `sub` claim
     ▼
get_customer_ref() ──► customer_ref: str ──► domain service
                                                   │
                                        find_X_for_customer(id, customer_ref)
```

This separation means: migrating from phone-based identity (`+966500000001`) to UUID-based identity (from an OIDC provider) is a change in `auth.py` and the token issuance pipeline — not in any domain service, aggregate, or repository.

**Constraint:** `customer_ref` must be stable for the lifetime of a customer's records. If the identifier changes (e.g. phone number is reassigned), a migration plan is required to update existing `customer_ref` values on Orders and Reservations. Changing `customer_ref` without migrating data severs the BOLA ownership link on historical records.

**Current value:** In v1.4, `customer_ref = reservation.customer_phone` (populated at reservation time, threaded to Order at checkout). When an OIDC provider is introduced, the JWT `sub` replaces phone as the authoritative identifier. The phone number moves to a profile attribute — not a principal identifier.

---

## Consequences

### Positive

**SEC-001 closed.** Admin endpoints now require `scope=admin` JWT. Customer endpoints require a valid JWT with `sub`. The test in `test_admin_scope_enforcement.py` is the machine-verifiable proof of both SEC-001 withdrawal conditions.

**Law 1 runtime-enforced.** JWT scope is validated per request on every non-public endpoint.

**Law 4 partial.** `scope=admin` vs `scope=customer` distinction is enforced at runtime. Full RBAC on capabilities within a scope is deferred — this is a scope-level distinction, not a capability-level one.

**Law 5 runtime-enforced.** BOLA check on order read endpoints is live: `OrderService.find_order_for_customer()` uses the JWT `sub` claim as `customer_ref`. The domain service owns the check, the router maps `None → 404`.

**`require_admin_secret` (X-Admin-Secret) is retired.** Removed from `shipments.py`. The SEC-001 withdrawal conditions are met.

### Watch Out For

**`POST /payments` — customer identity not yet threaded to domain.** The payment endpoint requires JWT (customer authenticated) but does not yet perform a BOLA check on the linked reservation. A customer with a valid JWT can initiate payment for a reservation they did not create. Fix in v1.4.1: verify `reservation.customer_ref == jwt_sub` before creating PaymentIntent.

**Rate limiting still not enforced.** Rate classes are declared; Redis enforcement is v1.4.1.

**HS256 → RS256 migration.** Required when a second service needs to verify tokens independently (e.g., a standalone auth service or another microservice). Plan a key rotation window; the `sub` and `scope` claim structure is stable.

**Pre-v1.4 orders.** Orders created before this Sprint have `customer_ref=NULL`. They cannot be fetched via `GET /api/v1/orders/{order_id}` by authenticated customers. This is the correct behavior — those orders are dev/test records with no verified customer identity.

---

## Test Inventory

| Test | File | What it proves |
|------|------|---------------|
| JWT decode (7 tests) | `test_jwt_auth.py` | Valid/expired/wrong-secret/missing-claims handling |
| Admin scope enforcement (7 tests) | `test_admin_scope_enforcement.py` | **SEC-001 withdrawal condition (2)** |
| Order BOLA (7 tests) | `packages/domain/tests/orders/test_order_bola.py` | Law 5 runtime — ownership in domain |

---

## Related

- ADR-017 — Security Architecture (SEC-001 withdrawal conditions defined here)
- ADR-010 — Webhook translation (Law 6 — no JWT on webhook endpoint)
- `apps/commerce-api/src/yasargold_commerce/auth.py` — implementation
- `packages/domain/src/yasargold_domain/orders/service.py` — `find_order_for_customer()`
