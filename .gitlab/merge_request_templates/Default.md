## Summary

<!-- One or two sentences: what does this MR do and why? -->

## Changes

<!-- Bullet list of the files/components changed and the reasoning. -->

---

## Review Checklist

### Architecture Gates (always required)

- [ ] **Law 0 (ADR-000):** Every new rule has a machine. Every new bug has a test that would have caught its class.
- [ ] **Contracts (CLAUDE.md):** No hand-editing of `packages/contracts/**`. No fabricated API shapes.
- [ ] **Copy (FC-5):** All Arabic customer-facing strings sourced from `lib/contract-copy.ts`.
- [ ] **Timers (FC-2):** No `Date.now()` in components — `lib/server-clock` only.
- [ ] **Tokens only:** No raw hex colours, no ad-hoc spacing/typography.
- [ ] **Security:** No secrets in code/logs/domain. External input validated at boundary.

### Frontend-specific (if `apps/web/**` touched)

- [ ] **State coverage:** Every new (component, state) pair registered in `STATE_STORY_REGISTRY`.
- [ ] **Stories prove states, pages prove journeys** — both required for new user-facing flows.
- [ ] **A11y:** `jsx-a11y` lint clean; interactive elements keyboard-reachable.
- [ ] **RTL:** Numbers render LTR tabular (`tabular-nums`, `dir="ltr"`) inside RTL layout.
- [ ] **Dep-cruiser:** `components/ → lib/api` is blocked; new context providers live in `lib/`.

### ERP Integration Gate (if `backend/**` touched for integration purposes)

> **ADR-023 M1 — The Seam Rule.**  
> *A touched ERP file with no Ledger row = review rejection.*

- [ ] **Seam Ledger row added:** `docs/architecture/erp-seam-ledger.md` has a new row for every `backend/` file touched for integration.
- [ ] **Contract tests added:** The Ledger row names specific test file(s) + count. If no tests (infrastructure-only touch), the reason is written in the Ledger row.
- [ ] **Ratchet checked:** `python scripts/erp_seam_ratchet.py` passes locally. If baseline improved, `--update` was run and the baseline file is committed.
- [ ] **Business logic moved to service** (if route logic was touched).
- [ ] **SQL moved out of route** (if SQL in route was touched).
- [ ] **Explicit transaction** (if transaction boundary was touched).

### ADR / Architecture Decision (if this MR makes a new architectural decision)

- [ ] **ADR written** in `docs/adr/ADR-NNN-*.md` with the mandatory `قانون أم سياسة؟` field.
- [ ] **Known Gaps updated** if a gap was opened, closed, or changed in `docs/architecture/architecture-v1.md §4.6`.

---

## Test Evidence

<!-- Paste the relevant test output. Red gate = MR is not ready. -->

```
# Example:
$ python -m pytest backend/ --tb=no -q
114 passed, 0 errors
```

---

## Related

- Issue / ticket: <!-- link -->
- ADR: <!-- link if applicable -->
