# ADR-006: Domain Owns Business State

**Status**: Accepted  
**Date**: 2026-07-12

## Rule

Any business concept with a lifecycle — states, transitions, expiry — must live in
`packages/domain`. Its states and transition rules may not be defined inside an API
layer, a router, or a UI component.

## Context

During Sprint 2, `QuoteStatus` was initially defined in `apps/commerce-api/schemas.py`
because it first appeared as a response field. This placed business logic inside the
API boundary.

The problem: when the Reservation Engine (Sprint 3) needed to enforce `FRESH → LOCKED`
transitions, it would have had to import from the API layer — inverting the dependency
direction.

## Decision

Moved `QuoteStatus` and the `Quote` Aggregate to
`packages/domain/src/yasargold_domain/pricing/quotes.py`.

`apps/commerce-api/schemas.py` imports and re-exports `QuoteStatus`; it owns no
business state itself.

## Consequences

**Dependency direction is now uniform:**
```
ERP  ──────────────────┐
Commerce API ──────────┼──▶ packages/domain ◀── Workers
Reservation Engine ────┘
```
All applications agree on the same Quote lifecycle definition.

**Validity requires both status and time.** The Aggregate enforces this rule:
```python
quote.can_reserve(now)  # status.allows_reservation AND valid_until >= now
```
Code that checks only `quote.status.allows_reservation` is incomplete and will be
caught in review.

**Audit is built into the Aggregate.** Every `Quote` carries `gold_price_id` and
`pricing_engine_version`, making every pricing decision fully traceable:
```
Order → Reservation → Quote → GoldPrice row
```

## Enforcement

- import-linter CI contract blocks `yasargold_domain` from importing `flask`,
  `fastapi`, `redis`, or `uvicorn`.
- Domain unit tests (`packages/domain/tests/`) run with zero infrastructure
  dependencies — no DB, no HTTP.
- Any PR that defines a business status enum outside `packages/domain` must be
  rejected in review citing this ADR.
