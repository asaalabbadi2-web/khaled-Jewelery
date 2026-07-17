# Gate A — Production Readiness Checklist

**Sprint:** 11 — External Providers  
**Date started:** 2026-07-15  
**Result:** ⏳ IN PROGRESS — see open items below

---

## Completed Items

### 1. ADR-019 Fakes — Every Protocol has a test double ✅

| Protocol | Fake class | File |
|----------|-----------|------|
| `PaymentGateway` | `FakePaymentGateway` | `payment/testing.py` |
| `RefundGateway` | `FakeRefundGateway` | `payment/testing.py` |
| `NotificationGateway` | `FakeNotificationGateway` | `notifications/testing.py` |
| `CarrierGateway` (`ShippingGateway`) | `FakeCarrierGateway` | `shipping/testing.py` |

4/4 Protocols have fakes. Domain tests use zero real adapters.

---

### 2. Import-linter — Domain never imports provider SDKs ✅

```
Analyzed 123 files, 559 dependencies.
Contracts: 1 kept, 0 broken.
```

0 violations. `packages/domain` contains no framework or SDK imports.

---

### 3. Staging E2E — Four integration scenarios ✅

| Scenario | Tests | Result |
|----------|-------|--------|
| Happy path (reserve → pay → order) | 6 | ✅ |
| Late webhook → refund (stock = 0 path) | 4 | ✅ |
| Duplicate webhook idempotency | 3 | ✅ |
| Refund retry (transient then success) | 3 | ✅ |

16/16 tests passing against in-process SQLite (StaticPool).  
**Note:** "Staging" here means in-process integration, not a provider sandbox environment.

---

### 4. Metrics naming — ADR-019 convention ✅

| Adapter | Metrics prefix | Kind label |
|---------|---------------|------------|
| `MoyasarRefundGateway` | `payment_refund_*` | `permanent` / `transient` |
| `TwilioNotificationGateway` | `sms_dispatch_*` | `permanent` / `transient` |
| `AramexCarrierGateway` (create) | `carrier_shipment_*` | `permanent` / `transient` |
| `AramexCarrierGateway` (void) | `carrier_void_*` | `permanent` / `transient` |

All 12 adapter-level metrics follow the ADR-019 naming convention.

---

### 5. ADR-019 Provider Inventory — Adapters complete ✅

| Provider | Protocol | Real Adapter | Fake | Unit Tests |
|----------|----------|--------------|------|------------|
| Moyasar (payments) | `PaymentGateway` | `MoyasarGateway` | `FakePaymentGateway` | Sprint 4 |
| Moyasar (refunds) | `RefundGateway` | `MoyasarRefundGateway` | `FakeRefundGateway` | 26 |
| SMS (Twilio) | `NotificationGateway` | `TwilioNotificationGateway` | `FakeNotificationGateway` | 28 |
| Carrier (Aramex) | `CarrierGateway` | `AramexCarrierGateway` | `FakeCarrierGateway` | 44 |

All adapters built and unit-tested. Provider sandbox verification: see open item below.

---

### 6. Full unit + integration test suite ✅

```
Domain (packages/domain):         334 passed, 0 failed
Commerce-API (apps/commerce-api): 373 passed, 0 failed
Total: 707 passed, 0 failed
```

---

### 7. ADR-019 Requirements — Per-adapter verification ✅

| Requirement | MoyasarRefundGateway | TwilioNotificationGateway | AramexCarrierGateway |
|-------------|---------------------|--------------------------|---------------------|
| ① Timeout | ✅ | ✅ | ✅ |
| ② Retry | ✅ 3 attempts (429+5xx) | ✅ budget=0 (SMS) | ✅ 3 attempts (429+5xx) |
| ③ Idempotency key | ✅ `Idempotency-Key` | ✅ `X-Twilio-Idempotency-Token` | ✅ caller key + `void:{tracking}` |
| ④ Correlation ID | ✅ `X-Correlation-Id` uuid4 | ✅ `X-Correlation-Id` uuid4 | ✅ `X-Correlation-Id` uuid4 |
| ⑤ Metrics | ✅ SUCCESS/FAILURE/DURATION | ✅ SUCCESS/FAILURE/DURATION | ✅ SUCCESS/FAILURE/DURATION ×2 |
| ⑥ Probe | ✅ any HTTP=True | ✅ 200=True, 401=False | ✅ any HTTP=True |
| ⑦ Availability/capability separation | ✅ | ✅ | ✅ |

All 7 ADR-019 principles verified in unit tests via MockTransport.

---

## Open Items — Gate A not yet closed

### OPEN-1: SEC-002 — Provider sandbox verification ⏳

**ADR-019 §Watch Out For:**
> No real adapter merges without a passing sandbox test. The sandbox test must cover the error path (provider returning 4xx) not just the happy path.

Current state: all 98 adapter tests use `httpx.MockTransport`. No live HTTP call has been made to any provider sandbox. MockTransport proves the adapter sends what we believe is correct — it does not prove the provider accepts it.

**Action required immediately (calendar-time dependency):**  
Sandbox account requests must be submitted in parallel today — before writing any test code. Aramex sandbox requires company registration and approval (days to weeks). Moyasar test mode and Twilio test credentials are faster but still require setup. Starting after the engineering work is done means idle waiting.

| Provider | Account request | Estimated lead time |
|----------|----------------|---------------------|
| Aramex | Sandbox account via Aramex developer portal | Days–weeks (requires company details) |
| Moyasar | Test API key (same account, toggle mode) | Same day |
| Twilio | Test credentials (trial account sufficient) | Same day |

**What each sandbox test must prove** (a 200 response is not sufficient):

**Moyasar refund sandbox:**
- [ ] A real refund call on a test payment reaches `REFUNDED` status (fetch the payment after and read status)
- [ ] Sending the same `Idempotency-Key` twice results in exactly one refund, not two
- [ ] A 4xx response (e.g. refunding an already-refunded payment) raises `RefundPermanentError`

**Twilio SMS sandbox:**
- [ ] Arabic template body is delivered to a Twilio test number (readable in Twilio console)
- [ ] Sending with the same `X-Twilio-Idempotency-Token` twice results in one message SID, not two
- [ ] An invalid `To` number returns 400 and raises `NotificationGatewayError` without retry

**Aramex carrier sandbox:**
- [ ] Created shipment: `declared_value` appears in the insurance field of the returned AWB — not the customs/duty field (read the shipment back via API and assert field name)
- [ ] Sending `create_shipment` with the same `Idempotency-Key` twice returns the same tracking number (one AWB)
- [ ] `void_shipment` within the void window cancels the AWB; a second void on the same tracking number returns a permanent error

**Gate condition:** All assertions above pass against the respective sandbox. Automated test preferred; documented manual run with output screenshot acceptable for Aramex if sandbox API is unstable.

**CI placement — sandbox tests do not run in the PR pipeline:**  
Provider sandbox environments are slow and flaky by nature. Putting them in the PR gate turns every merge into a bet on Aramex's network mood. The correct structure:

- The 98 `MockTransport` tests run on every PR — they guard the code.
- Sandbox tests run as a separate job (manual trigger or nightly schedule), marked `@pytest.mark.sandbox`, excluded from the default test run via `pytest -m "not sandbox"`.
- **One passing documented run** is the closure condition for OPEN-1.
- **Continuing nightly runs** serve as an early-warning system for silent provider API changes — which happen more often than their contracts promise.

The MockTransport tests guard the PR boundary. The sandbox tests guard the provider boundary. They answer different questions and belong in different pipelines.

---

### OPEN-2: Reconciliation alert — `reconciliation_gaps_total` ✅ CLOSED (2026-07-15)

Original Gate A definition included:
> (4) reconciliation_gaps_total alert in monitoring stack

**Step A — Steady-state (zero gaps):** Covered by `TestStepAZeroGaps` — 3 tests against real SQLite DB prove the worker runs cleanly with no PAID orders, with matching invoices, and with an unreachable ERP (network errors do not become gaps).

**Step B — Synthetic gap injection:** Covered by `TestStepBMissingInvoiceGap` and `TestStepBAmountMismatchGap` — 8 tests use a real SQLAlchemy session to prove:
- `reconciliation_findings` row inserted with correct `kind` and `resolved_at = NULL`
- `RECONCILIATION_GAPS.labels(kind=...)` counter incremented by exactly 1
- Mixed-order scenario: only the gapped order produces a finding row

File: `tests/contract/reconciliation/test_reconciliation_gap_injection.py` (12 tests, all passing)

**Prometheus alert rule** (apply to `prometheus/alerts.yml`):

```yaml
groups:
  - name: commerce_reconciliation
    rules:
      - alert: ReconciliationGapDetected
        expr: increase(reconciliation_gaps_total[1h]) > 0
        for: 0m
        labels:
          severity: critical
          team: commerce
        annotations:
          summary: "Commerce reconciliation gap detected"
          description: >
            {{ $value }} gap(s) found between Commerce orders and ERP invoices
            in the last hour. Check reconciliation_findings table and investigate
            before real transactions resume. kind={{ $labels.kind }}
```

**Gate condition:** Step A ✅ + Step B ✅ + alert rule above applied to monitoring stack (pending deploy — no Prometheus stack in staging yet; rule is ready).

---

## Scope note — Gate A does not mean all inventory is live

Gate A = Moyasar production keys are safe to activate.  
Gate B (POS UI consuming the availability endpoint) is still open.

Until Gate B closes, the operational rule is:
**Only items confirmed absent from the physical showroom are eligible for online listing.**

INV-4 is the failure mode if this rule is violated: a customer buys online an item that was simultaneously sold at the counter. The `ReconciliationWorker` is the detection mechanism (not prevention), which is a further reason OPEN-2 must be resolved before real transactions begin.

---

## Gate A — Closure Criteria

Gate A is closed when all of the following are true:

- [x] Adapters built and unit-tested (items 1–7 above)
- [x] **OPEN-2:** ReconciliationWorker gap injection proven (12 tests, real SQLite); Prometheus alert rule ready
- [ ] **SEC-002:** Moyasar refund sandbox test passing
- [ ] **SEC-002:** Twilio SMS sandbox test passing
- [ ] **SEC-002:** Aramex carrier sandbox test passing
- [ ] **OPEN-2 (ops):** Apply alert rule YAML to Prometheus stack when staging env is available
