# Payment Security & Compliance Brief — yasargold Commerce Platform

**Prepared for:** Payment gateway compliance review (Moyasar merchant activation)  
**Derived from:** `docs/security/security-overview.md` (canonical) — per platform documentation policy §12  
**Last reconciled with canonical document:** 2026-07-16  
**Platform test suite at reconciliation:** 765 automated tests · 104 security-specific · 0 failures  
**Contact:** [name / email / role]

---

## 1. Platform Overview

yasargold operates an e-commerce platform for fine gold jewellery in Saudi Arabia.
The platform consists of a public commerce API (Python/FastAPI), a customer web storefront
(in development), and an internal ERP for showroom operations. All payment processing is
delegated to the payment gateway; the platform orchestrates order lifecycle, inventory
reservation, and fulfilment.

---

## 2. Cardholder Data — Not Stored, Not Processed, Not Transmitted

- Checkout uses the **gateway-hosted payment page**. The customer enters card details on
  the gateway's domain (`transaction_url` redirect); card data never reaches yasargold
  servers, applications, or logs.
- The platform stores only: payment-intent identifiers issued by the gateway, payment
  status, amounts, and timestamps.
- No PAN, CVV, expiry, or cardholder name is persisted or transited anywhere in the
  platform.
- Consequently the platform targets the minimal PCI DSS self-assessment profile applicable
  to fully hosted / redirect integrations. [confirm exact SAQ level with gateway]

---

## 3. Authentication & Access Control

- All API access is authenticated with **JWT**; authorization uses capability scopes
  (`customer`, `admin`).
- **Deny-by-default is enforced structurally:** every API route must carry a declared
  security classification; an unclassified route fails the build and cannot be deployed.
  This is verified automatically on every code change.
- Administrative operations (refund handling, shipment control) require admin scope;
  enforcement is proven in both directions by automated tests (customer credentials are
  rejected on admin endpoints with HTTP 403).
- Object-level access control: customers can access only their own orders and reservations;
  ownership is verified in the service layer, and non-owned resources return HTTP 404
  (resource existence is not disclosed).

---

## 4. Data Protection

- **In transit:** TLS on all external communication (client ↔ platform, platform ↔ gateway).
  Internal service-to-service calls are authenticated with verified shared secrets
  (constant-time comparison); migration to mutual TLS is planned.
- **Secrets management:** credentials (including gateway API keys) exist only as environment
  variables in deployment configuration; they are never present in source code, in the
  business-logic layer (enforced by automated import analysis), or in logs (a redaction
  filter rewrites authorization headers, tokens, and API keys before any log handler runs —
  verified by automated tests).
- **Fail-closed posture:** if a required security dependency (e.g., the rate-limiting store)
  is missing in production configuration, the application refuses to start rather than
  degrading silently.

---

## 5. Webhook Handling

- Gateway webhooks are accepted only after **signature verification**; a payload with an
  invalid signature is rejected (HTTP 400) before any business logic executes — proven by
  automated tests.
- Processing is **idempotent** by gateway event ID: redelivered webhooks are acknowledged
  without double-processing (duplicate → HTTP 204).
- Webhook traffic has a dedicated rate-limit class, isolated from customer traffic, so
  gateway retries are never throttled.
- Webhooks are acknowledged quickly and processed asynchronously by workers, ensuring no
  event loss during transient application errors.

---

## 6. Refunds

- Refunds follow a controlled state machine (`REFUND_PENDING → REFUNDED`) executed by a
  dedicated worker through the gateway's refund API, with idempotency keys on every call.
- A database-level constraint guarantees total refunds can never exceed the amount captured
  for an order.
- The primary automated refund scenario: if payment succeeds after the underlying inventory
  reservation has expired, the platform refunds automatically without manual intervention —
  covered by end-to-end tests.

---

## 7. Reconciliation & Monitoring

- A **daily reconciliation job** compares gateway records, platform payment records, and ERP
  accounting entries. Every discrepancy creates a persistent finding that remains open until
  explained, increments a monitored metric, and triggers an alert.
- Detection capability is itself tested: automated tests inject synthetic discrepancies and
  verify the finding, the metric, and the alert fire.
- Operational monitoring: success/failure counters and latency histograms on every gateway
  interaction; alerting on refund failures, reconciliation gaps, and processing lag.

---

## 8. Change Control & Assurance

- Security properties are expressed as automated tests executed on every code change; a
  change that violates them cannot be merged.
- Architectural decisions are recorded in numbered ADRs (19 to date); security posture and
  known limitations are documented in a single canonical document with dated reconciliation.
- Known open items are tracked with explicit exposure statements and target resolutions, and
  are available to the reviewer on request.

---

## 9. Requested from the Gateway

To complete integration readiness, yasargold requests:

1. Sandbox/test credentials for end-to-end verification of payment, refund, and webhook
   flows (test assertions already prepared — pending credentials only).
2. The gateway's merchant activation / compliance checklist, to reconcile this brief against
   the gateway's specific requirements.

---

*This brief is a derived summary. The canonical technical reference (`security-overview.md`,
with test-level evidence) can be shared with the compliance team under NDA on request.*
