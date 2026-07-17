# ADR-009: External Providers Are Adapters

**Status**: Accepted  
**Date**: 2026-07-13

## Rule

The domain (`packages/domain`) must never know the name, API format, HTTP
endpoints, authentication scheme, or webhook signature format of any external
provider. Every external service is an Adapter behind a domain-owned Protocol.

## Context

As the platform grows, it will integrate with multiple external providers:

- **Payment gateways**: Moyasar, Tap, HyperPay
- **Gold price feeds**: external APIs, bank feeds
- **SMS / push notifications**: Twilio, Unifonic, Infobip
- **Shipping**: Aramex, SMSA, Naqel
- **Email**: SendGrid, SES

Without a formal rule, each integration risks leaking provider-specific
concepts into domain services. Signs of leakage:

```python
# BAD — provider name branches in domain code
if provider == "moyasar":
    headers = {"Authorization": f"Basic {moyasar_key}"}
elif provider == "tap":
    headers = {"Authorization": f"Bearer {tap_key}"}

# BAD — provider response shape in domain model
intent.moyasar_id = response["id"]        # field name is provider-specific
intent.tap_charge_id = response["charge"] # two fields for one concept
```

Once provider logic enters the domain, it cannot be replaced without domain
changes, and testing requires network access to the provider.

## Decision

Every external provider is an Adapter implementing a domain-owned Protocol.

### The Protocol lives in `packages/domain`

```python
# packages/domain/src/yasargold_domain/payment/gateway.py
class PaymentGateway(Protocol):
    def initiate(self, intent: PaymentIntent, callback_url: str) -> CheckoutUrl: ...
    def parse_webhook(self, payload: bytes, signature: str) -> WebhookResult: ...
```

The Protocol uses only domain value objects (`PaymentIntent`, `CheckoutUrl`,
`WebhookResult`). It never mentions HTTP, JSON, API keys, or provider names.

### The Adapter lives in `apps/` or `infra/`

```python
# apps/commerce-api/infra/moyasar_gateway.py
class MoyasarGateway:
    def initiate(self, intent: PaymentIntent, callback_url: str) -> CheckoutUrl:
        # Authorization header, REST call, JSON parsing — all here
        ...

    def parse_webhook(self, payload: bytes, signature: str) -> WebhookResult:
        # HMAC verification, status code mapping — all here
        ...
```

### The FakeGateway lives in `packages/domain` (test helper)

```python
# packages/domain/src/yasargold_domain/payment/testing.py
class FakePaymentGateway:
    """In-memory stub used by domain tests and Commerce API integration tests.
    Zero network calls. Configurable outcomes."""
```

## What belongs where

| Concern | Location |
|---|---|
| `PaymentGateway` Protocol | `packages/domain/payment/gateway.py` |
| `CheckoutUrl`, `WebhookResult` | `packages/domain/payment/gateway.py` |
| `FakePaymentGateway` (test stub) | `packages/domain/payment/testing.py` |
| `MoyasarGateway` (production) | `apps/commerce-api/infra/moyasar_gateway.py` |
| Moyasar API keys, base URL | Environment config, never committed |
| HMAC verification logic | `MoyasarGateway.parse_webhook()` only |
| Retry policy, HTTP timeouts | `MoyasarGateway` only |

## Invariants

1. `packages/domain` imports zero HTTP libraries (`requests`, `httpx`, `aiohttp`).
2. `packages/domain` contains no provider names as behaviour-branching strings.
3. `provider: PaymentProvider | None` on `PaymentIntent` is a metadata label
   for audit logs — domain code never branches on its value.
4. `provider_reference` is an opaque string — the domain never inspects its format.
5. Swapping a payment provider requires adding one new Adapter file. Zero domain changes.

## Scope beyond payments

This rule applies to all external integrations. New capability checklist:

- [ ] Define Protocol in `packages/domain` (or `packages/platform`)
- [ ] Define input/output value objects in the Protocol file
- [ ] Implement `Fake*` in `packages/domain/.../testing.py`
- [ ] Implement real Adapter in `apps/commerce-api/infra/`
- [ ] Domain tests use Fake only — zero network in domain test suite
- [ ] Integration tests use real Adapter in a controlled environment

## Consequences

**Adding a second payment provider** = one new file in `apps/commerce-api/infra/`.
No changes to `PaymentIntent`, `PaymentService`, or any domain test.

**Domain tests are network-free** — `pytest packages/domain/` passes on a
machine with no internet, no API keys, no Docker.

**Replacing a provider** = swap the Adapter registered in the DI container.
Zero downtime if both Adapters are deployed simultaneously.

## Enforcement

Any PR that imports `requests`, `httpx`, or a provider SDK into `packages/domain`
must be rejected in review citing this ADR.

Import-linter rule (to be added to `.importlinter`):

```ini
[importlinter:contract:no-http-in-domain]
name = Domain must not import HTTP libraries
type = forbidden
source_modules =
    yasargold_domain
forbidden_modules =
    requests
    httpx
    aiohttp
    urllib3
```
