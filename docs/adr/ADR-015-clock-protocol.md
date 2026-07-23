# ADR-015 — Clock Protocol: Inject `now` as a Parameter

**Status:** Accepted
**Date:** 2026-07-14
**Sprint:** 7 — Shipping

---

## Context

The Shipping capability introduced `can_void(now, void_window)` — a pure function
on the `Shipment` aggregate that determines whether a shipment can still be cancelled
within the carrier's void window. The function takes two external parameters:

- `void_window: timedelta` — Live (read from `CarrierConfig` by the caller)
- `now: datetime` — the current instant

This was our first place where "what time is it right now?" is a decision input.
The pattern had already silently appeared in `NotificationService.dispatch()` via
`now: datetime | None = None` → `now or datetime.now(timezone.utc)`, but Sprint 7
elevated it to a first-class architectural principle: **the clock is an external
dependency, just like a database or a gateway**.

---

## Decision

All domain methods that need the current time receive `now: datetime` as an
explicit parameter. No domain code calls `datetime.now()` internally unless the
parameter is `None` (backward-compat default for service methods that pre-date
this ADR).

```python
# WRONG — hardwired clock
def can_void(self) -> bool:
    return datetime.now(timezone.utc) < self.registered_at + void_window

# RIGHT — injected clock + injected void_window
def can_void(self, now: datetime, void_window: timedelta) -> bool:
    return (
        self.status == ShipmentStatus.CREATED
        and self.registered_at is not None
        and now < self.registered_at + void_window
    )
```

**Callers** (routers, workers) call `datetime.now(timezone.utc)` once at the
boundary and pass it down. Tests pass a fixed `_NOW` constant — no patching,
no `freezegun`, no mocking.

---

## Consequences

### Positive

**Tests are time-stable.** `test_shipment.py` uses:
```python
_NOW = datetime(2026, 7, 14, 10, 0, 0, tzinfo=timezone.utc)
```
These tests never expire. Compare with the Sprint 6 incident where hardcoded
`_NOW = datetime(2026, 7, 13, ...)` caused failures the next day.

**void_window boundary tests are trivial.** `TestSM4CanVoidAfterWindowExpires`
passes `_NOW + timedelta(hours=6)` vs `_NOW + timedelta(hours=7)` without any
time-travel library. Two lines per test, zero infrastructure.

**Two-carrier tests** (`TestSM12TwoCarriersDifferentVoidWindows`) demonstrate the
dual benefit: the same `now` value with two different `void_window` values produces
different results — proving that `void_window` is truly Live (read from config at
decision time, not cached on the aggregate).

**`can_void` is a pure function.** Given the same inputs, it always returns the
same output. This makes it trivially testable, serializable, and auditable
("at T+3h with a 6h window, the void was valid").

### Neutral

Callers must remember to pass `now`. For router-level code, this is one line:
`now = datetime.now(timezone.utc)`. The pattern is already established in every
router in this codebase.

### Watch out for

Service methods with `now: datetime | None = None` defaults (the pre-ADR pattern)
are backward-compatible but mask the injection when `None` is passed. New service
methods added after this ADR should require `now: datetime` (no default). Existing
methods (`OrderService.ship()`, `OrderService.deliver()`) retain the `None` default
for compatibility.

---

## Applicability

This protocol applies to:

| Context | Method | now source |
|---------|--------|------------|
| Shipping | `Shipment.can_void(now, void_window)` | Injected by caller |
| Shipping | `ShipmentService.claim(…, now, …)` | Router boundary |
| Shipping | `ShipmentService.mark_created(…, now, …)` | Router boundary |
| Shipping | `ShipmentService.void(…, now, …)` | Router boundary |
| Notifications | `NotificationService.dispatch(…, now, …)` | Worker boundary |
| Orders | `OrderService.ship(…, now)` | Shipments router boundary |

Any future capability that makes a time-dependent decision (expiry, rate freshness,
promotion validity) MUST follow this protocol from day one.

---

## Clock Discipline

### Two kinds of time

The system distinguishes two fundamentally different uses of "now":

**PRESENTATION TIME (UI)** — the UI must display how long until a reservation
expires, how fresh the gold price is, and similar live countdowns. The client's
system clock is untrusted (skew up to ±hours observed in the wild). The frontend
obtains the current time via `serverNow` / `syncServerClock` per **FC-2** of the
Frontend Constitution. A server-anchored offset is maintained in the browser so
all countdowns and freshness labels are anchored to server time — never to
`Date.now()`.

**DECISION TIME (Domain and Workers)** — any operation that **changes system
state** — reservation expiry, claim TTL enforcement, payment-intent voiding,
reconciliation windows, gold-price freshness gates — must obtain time via the
**injected Clock Provider** defined in this ADR. The caller passes `now: datetime`
as an explicit parameter; the domain function uses that value and never calls
`datetime.now()` internally.

The **ultimate source** for decisions tied to durable state (`Reservation`,
`Order`, `PosClaim`, `Shipment`) is the **database clock** (`SELECT NOW()` or
equivalent, read once per transaction boundary and threaded through as the
injected `now`). Container NTP keeps clocks close for **logs, metrics, and trace
timestamps only** — it is not a source for business decisions.

### Why the distinction matters

An NTP-synchronised container clock still drifts ±100 ms–5 s against the DB
clock. For gold-price freshness windows measured in minutes and reservation TTLs
measured in seconds, that drift can produce incorrect expiry decisions. Injection
makes the time source explicit and testable: the domain unit-test passes a fixed
`_NOW` constant; production passes the DB clock read at the transaction boundary.
The host system clock never enters the decision path.

Proof: `packages/domain/tests/shipping/test_clock_discipline.py` (Baseline +
HostDrift classes) demonstrates that patching `datetime.now` in the module has no
effect on the decision when `now` is injected correctly — and that the direction of
drift does not matter.

### Enforcement

`scripts/clock_guard.py` scans decision-path directories for bare
`datetime.now()` / `datetime.utcnow()` calls and fails CI on any unacknowledged
violation.

- **Scanned:** `packages/domain/src/`, `apps/commerce-api/src/yasargold_commerce/workers/`, `backend/services/`
- **Exempt:** `return datetime.now(` (clock-factory); ` or datetime.now(` (injection fallback); `testing.py` files

Suppression taxonomy (inline comment required):

| Tag | Meaning | Counted in ratchet? |
|-----|---------|-------------------|
| `# clock-guard: boundary` | ADR-015 boundary caller — worker/router reads the clock once and passes it down | ❌ No |
| `# clock-guard: TIME-001` | Known Gap — legacy decision-path call, tracked and shrinking | ✅ Yes |
| `# clock-guard: record-only` | Audit/display timestamp; no downstream decision reads this value | ❌ No |

**Ratchet:** `docs/architecture/.clock-debt-baseline` holds the committed count of `TIME-001` suppressions. CI fails if the count increases. To lower the baseline after genuine removals: `python scripts/clock_guard.py --update` (only in the same PR that removes suppressions).

---

## Related

- ADR-014 — Notifications provider-agnostic (first `now` parameter appearance)
- §13 of `architecture-v1.md` — Frozen vs Live value reference
- `packages/domain/tests/shipping/test_shipment.py` — SM3/SM4/SM12 demonstrate
  the protocol in action without any mocking library
