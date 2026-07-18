# ADR-021 — Frontend Browser-Walkability Rule

**Status:** Accepted  
**Date:** 2026-07-18  
**Scope:** `apps/web`

## Context

The platform's UI is verified at two levels:

1. **Storybook stories** — isolated component states in a harness. Fast, exhaustive at the component level, but cannot verify that states connect to each other or that MSW handlers return the right shapes.
2. **Playwright E2E** — full browser runs that cross multiple states in sequence. Slow but definitive.

A gap exists: a story that renders `OTP_SENT` state correctly tells you nothing about whether the ENTRY → OTP_SENT transition actually fires when the user submits the form. Component tests pass; the journey breaks.

## Decision

**Every user-facing flow in `apps/web` must be walkable in a real browser against MSW before it can be merged.** This means:

- The happy path of each flow (browse → product → reserve → checkout → success, track → OTP → order) must be completed end-to-end in a Chromium browser driven by Playwright.
- MSW must intercept all API calls; no real backend is required.
- The walkability test lives in `apps/web/e2e/` and is a **journey test**, not a visual test — it asserts state transitions (URL, visible text, aria-label) not pixel coordinates.

### What qualifies as a "flow"

| Flow | Entry point | Terminal state |
|------|-------------|----------------|
| Browse → Product | `/jewellery/[category]` | Product page data matches catalog |
| Reserve → Checkout | «احجز» button | `SUCCESS` state with order ID |
| Track OTP | `/track` ENTRY | `ORDER_ACTIVE` with carrier row |
| 404 recovery | invalid URL | any browsing page via secondary CTA |

### What does NOT satisfy this rule

- A Storybook story that shows the state.
- A unit test that calls the state machine directly.
- Manual QA notes without a committed test.

## Consequences

**Positive:**
- Regressions in MSW handler shapes surface immediately in CI.
- New flows cannot be merged without a matching journey test — prevents the recurring pattern of "stories pass, page breaks on first real click".

**Negative:**
- Journey tests are slower than unit tests (~5–10 s per flow). Acceptable given the flow count.
- MSW must be kept in sync with handler contract; stale handlers are now a CI failure risk, not just a dev nuisance.

## Enforcement

The E2E suite at `apps/web/e2e/` runs in CI via `playwright test --project=chromium`. A new flow is blocked from merge if no journey test covers its terminal state.
