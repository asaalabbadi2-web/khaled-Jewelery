# ADR-019 — External Providers Are Replaceable Infrastructure

**Status:** Accepted
**Date:** 2026-07-14
**Sprint:** 11 — Production Readiness (Gate A)

---

## Context

As of Sprint 11, the platform connects to its first real external providers:
- **Moyasar** — payment processing and refunds
- **SMS provider** (Twilio / unifonic) — customer notifications
- **Carrier** (Aramex / SPL / DHL) — shipment creation and void

A pattern had already emerged in the codebase by Sprint 4: `PaymentGateway` (Protocol) with `MoyasarGateway` (implementation) and `FakePaymentGateway` (test double). This ADR formalizes that pattern as a platform-wide law before the remaining providers are built, and defines the constraints every provider integration must satisfy.

---

## Decision

### The Law

> **Every external provider is hidden behind a Protocol. The domain never imports a provider SDK. Every provider has a fake for tests.**

This is not a preference — it is a structural constraint enforced by `import-linter` (Law 2, face 1) and the fake requirement enforced by the contract test suite.

### Provider Integration Pattern

```
packages/domain/
    yasargold_domain/{capability}/gateway.py   ← Protocol only. No imports from any SDK.

apps/commerce-api/
    yasargold_commerce/infra/{provider}_gateway.py   ← Implements the Protocol. SDK lives here.

packages/domain/
    yasargold_domain/{capability}/testing.py   ← Fake implementation. Used in all domain tests.
```

**Naming:**
- Protocol: `PaymentGateway`, `RefundGateway`, `NotificationGateway`, `CarrierGateway`
- Real adapter: `MoyasarGateway`, `MoyasarRefundGateway`, `TwilioNotificationGateway`, `AramexCarrierGateway`
- Test double: `FakePaymentGateway`, `FakeRefundGateway`, `FakeNotificationGateway`, `FakeCarrierGateway`

The Protocol name names the capability. The adapter name names the company. The domain only ever sees the capability name.

### Required for Every Real Adapter

| Requirement | Rationale |
|-------------|-----------|
| **Timeout** on every outbound call | Prevents a slow provider from blocking the request thread indefinitely |
| **Retry** on transient errors only (connection reset, 429, 503) | Non-idempotent calls must not retry on 400/404/409; retrying those causes duplicate side-effects |
| **Idempotency key** on all write operations | Enables safe retry without duplicate charges/shipments |
| **Correlation ID** in every outbound request header | Links provider logs to our logs — mandatory for incident investigation |
| **Metrics** — success counter, error counter, duration histogram | Matches the observability level of all domain workers |
| **Sandbox test** required before merging any real adapter (SEC-002) | No real adapter merges without a passing test against the provider's sandbox/test environment |
| **Availability/capability separation** — `probe()` answers "can I reach the provider?"; business methods answer "did the operation succeed?" | A provider can be reachable but refuse a specific refund (business failure); a provider can accept a call but be unreachable for probes (routing anomaly). Mixing the two signals corrupts dashboards and triggers wrong alerts |

### Availability vs Capability — Why the Distinction Matters

Every adapter exposes two categories of signal:

| Signal | Method | Question answered | Alert target |
|--------|--------|------------------|--------------|
| **Transport availability** | `probe()` | Can we reach the provider's API at all? | On-call infrastructure alert — network / DNS / TLS |
| **Business capability** | `refund()`, `dispatch()`, `create_shipment()` | Did the provider accept and process this specific operation? | Business alert — high failure rate, manual queue growing |

**A provider can be available but not capable:**
`probe()` returns `True` (API responds), but `refund("pay_abc")` returns 409 (already refunded).
This is a business failure, not an infrastructure failure. Paging on-call for a 409 is noise.

**A provider can be capable but temporarily unavailable:**
`probe()` times out (network blip), but the last 100 `refund()` calls all succeeded and the queue is draining normally.
This is infrastructure transience, not a business problem.

**Dashboard consequence:**
- **Provider Up/Down panel:** driven by `probe()` — one row per provider, binary status
- **Refund success rate panel:** driven by `payment_refund_success_total` vs `payment_refund_failure_total` — SLO line at 99.5%
- **Alert rule:** page on-call only when BOTH probe fails AND failure rate rises — avoids false pages on isolated business rejections

### Metrics Naming Convention

```
{capability}_{operation}_success_total    (Counter)
{capability}_{operation}_failure_total    (Counter, labelnames=["kind"])
{capability}_{operation}_duration_seconds (Histogram)
```

Examples:
```
payment_refund_success_total
payment_refund_failure_total{kind="gateway_error"}
payment_refund_duration_seconds
sms_dispatch_success_total
carrier_shipment_success_total
```

### What the Domain Does NOT Know

| The domain never knows… | It knows instead… |
|-------------------------|-------------------|
| That Moyasar exists | That a `PaymentGateway` was injected |
| That Aramex exists | That a `CarrierGateway` was injected |
| That Twilio exists | That a `NotificationGateway` was injected |
| Provider error codes | Typed domain exceptions (`ShipmentGatewayError`, `MoyasarSignatureError`) |
| Provider API shapes | Its own Protocol method signatures |

Provider-specific errors are translated at the adapter boundary into domain exceptions before they cross into domain code.

### Fake Requirements

Every Protocol must have a `Fake{Name}` in `{capability}/testing.py` that:
1. Implements the Protocol without any network calls
2. Stores side-effects in memory (`.calls`, `.sent_messages`, `.shipments_created`)
3. Can be configured to fail on demand (`fail_on_next=True`)
4. Is used by all domain tests — real adapters are never used in domain tests

---

## Provider Inventory

| Provider | Protocol | Real Adapter | Fake | Status |
|----------|----------|--------------|------|--------|
| Moyasar (payments) | `PaymentGateway` | `MoyasarGateway` | `FakePaymentGateway` | ✅ Sprint 4 |
| Moyasar (refunds) | `RefundGateway` | `MoyasarRefundGateway` | `FakeRefundGateway` | ✅ Sprint 11.1 (26 tests) |
| SMS provider | `NotificationGateway` | `TwilioNotificationGateway` | `FakeNotificationGateway` | ✅ Sprint 11.3 (28 tests) |
| Carrier | `CarrierGateway` | `AramexCarrierGateway` | `FakeCarrierGateway` | ✅ Sprint 11.4 (44 tests) |

---

## Consequences

### Positive

**Provider swaps are infrastructure changes.** Replacing Aramex with SPL means writing a new `SPLCarrierGateway` that implements `CarrierGateway` — the domain, contract tests, and integration tests are unchanged.

**Tests never call real providers.** Domain tests use fakes; contract tests use fakes or stubs. The only tests that call real providers are the staging E2E tests (Sprint 11), which run in CI against provider sandboxes.

**Incidents are diagnosable.** Correlation IDs + metrics per provider mean that when Moyasar returns a 502, there is a specific metric that moves, a specific log entry with a request ID, and a specific alert threshold.

### Watch Out For

**Do not add provider SDK imports inside `packages/domain`** — import-linter will catch this, but the violation will waste a CI cycle. Add the import to `apps/commerce-api/src/yasargold_commerce/infra/` instead.

**Retry budget must match idempotency guarantee.** If the provider does not guarantee idempotency on retries, do not retry. Moyasar refunds use an idempotency key — retries are safe. SMS sends without an idempotency key — retry budget is 0.

**SEC-002:** No real adapter merges without a passing sandbox test. The sandbox test must cover the error path (provider returning 4xx) not just the happy path.

---

## Related

- ADR-009 — Providers Are Adapters (Payment domain)
- ADR-010 — Webhook Translation Layer
- `packages/domain/src/yasargold_domain/payment/gateway.py` — canonical Protocol example
- `packages/domain/src/yasargold_domain/payment/testing.py` — canonical Fake example
