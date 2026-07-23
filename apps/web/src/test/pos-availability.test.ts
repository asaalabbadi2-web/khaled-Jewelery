/**
 * Gate B Frontend — PosAvailabilityGate logic tests.
 *
 * These tests prove the 8 acceptance criteria from the Sprint 10 brief using
 * pure exported functions. No rendering required — this keeps the tests fast
 * and removes the @testing-library/react dependency.
 *
 * Coverage matrix:
 *   F1  available item → AVAILABLE state (canProceed=true)
 *   F2  reserved item  → RESERVED state (canProceed=false)
 *   F3  unavailable item (available=false) → blocked (same API shape as F2)
 *   F4  Commerce timeout → TIMEOUT state (fail-open, canProceed=true)
 *   F5  Commerce unreachable → UNREACHABLE state (fail-open, canProceed=true)
 *   F6  operator retry: re-check after RESERVED → new state from domain
 *   F7  zero invoice creation before positive availability (canProceed gate)
 *   F8  correct UX message for every domain state → STATE_STORY_REGISTRY
 *       (6 stories in PosAvailabilityGate.stories.tsx, verified by state-coverage.test.ts)
 *
 * Fail-open policy: mirrors backend Gate B (services/commerce_availability.py).
 * ADR-016 § Gate B: timeout / unreachable → sale allowed + warning shown.
 */
import { describe, it, expect } from 'vitest'
import {
  posCheckCanProceed,
  apiResponseToPosCheckState,
  errorToPosCheckState,
  type PosCheckState,
} from '@/components/pos/PosAvailabilityGate'

// ── F1 — Available item ───────────────────────────────────────────────────────

describe('F1: available item', () => {
  it('available=true → AVAILABLE state', () => {
    const state = apiResponseToPosCheckState({
      available:      true,
      reserved_until: null,
      reservation_id: null,
    })
    expect(state.kind).toBe('AVAILABLE')
  })

  it('AVAILABLE → canProceed (sale may be confirmed)', () => {
    expect(posCheckCanProceed({ kind: 'AVAILABLE' })).toBe(true)
  })
})

// ── F2 — Reserved item ────────────────────────────────────────────────────────

describe('F2: reserved item', () => {
  const UNTIL = '2026-07-19T15:00:00+03:00'
  const RID   = 'RES-4a9f1'

  it('available=false → RESERVED state', () => {
    const state = apiResponseToPosCheckState({
      available:      false,
      reserved_until: UNTIL,
      reservation_id: RID,
    })
    expect(state.kind).toBe('RESERVED')
  })

  it('RESERVED preserves reservedUntil and reservationId from domain', () => {
    const state = apiResponseToPosCheckState({
      available:      false,
      reserved_until: UNTIL,
      reservation_id: RID,
    })
    if (state.kind !== 'RESERVED') throw new Error('Expected RESERVED')
    expect(state.reservedUntil).toBe(UNTIL)
    expect(state.reservationId).toBe(RID)
  })

  it('RESERVED → canProceed=false (sale is blocked)', () => {
    const state: PosCheckState = {
      kind:          'RESERVED',
      reservedUntil: UNTIL,
      reservationId: RID,
    }
    expect(posCheckCanProceed(state)).toBe(false)
  })
})

// ── F3 — Unavailable item (available=false, same wire shape) ─────────────────

describe('F3: unavailable item', () => {
  it('any available=false response → blocked regardless of IDs', () => {
    const state = apiResponseToPosCheckState({
      available:      false,
      reserved_until: '2026-07-20T10:00:00Z',
      reservation_id: 'RES-XYZ',
    })
    expect(posCheckCanProceed(state)).toBe(false)
  })
})

// ── F4 — Commerce timeout ─────────────────────────────────────────────────────

describe('F4: Commerce timeout', () => {
  it('AbortError (DOMException) → TIMEOUT state', () => {
    const state = errorToPosCheckState(
      new DOMException('Gate B timeout', 'AbortError'),
    )
    expect(state.kind).toBe('TIMEOUT')
  })

  it('AbortError (plain Error) → TIMEOUT state', () => {
    const err = Object.assign(new Error('aborted'), { name: 'AbortError' })
    const state = errorToPosCheckState(err)
    expect(state.kind).toBe('TIMEOUT')
  })

  it('TIMEOUT → canProceed=true (fail-open, matches backend policy)', () => {
    expect(posCheckCanProceed({ kind: 'TIMEOUT' })).toBe(true)
  })
})

// ── F5 — Commerce unreachable ─────────────────────────────────────────────────

describe('F5: Commerce unreachable', () => {
  it('TypeError (network failure) → UNREACHABLE state', () => {
    const state = errorToPosCheckState(new TypeError('fetch failed'))
    expect(state.kind).toBe('UNREACHABLE')
  })

  it('unknown error object → UNREACHABLE state', () => {
    const state = errorToPosCheckState(new Error('connection refused'))
    expect(state.kind).toBe('UNREACHABLE')
  })

  it('UNREACHABLE → canProceed=true (fail-open, matches backend policy)', () => {
    expect(posCheckCanProceed({ kind: 'UNREACHABLE' })).toBe(true)
  })
})

// ── F6 — Operator retry ───────────────────────────────────────────────────────

describe('F6: operator retry', () => {
  it('re-checking after RESERVED returns fresh state from domain', () => {
    // First check: reservation active → blocked.
    const firstCheck = apiResponseToPosCheckState({
      available:      false,
      reserved_until: '2026-07-19T15:00:00+03:00',
      reservation_id: 'RES-001',
    })
    expect(firstCheck.kind).toBe('RESERVED')
    expect(posCheckCanProceed(firstCheck)).toBe(false)

    // Reservation expires between checks; Commerce now returns available=true.
    const afterRetry = apiResponseToPosCheckState({
      available:      true,
      reserved_until: null,
      reservation_id: null,
    })
    expect(afterRetry.kind).toBe('AVAILABLE')
    expect(posCheckCanProceed(afterRetry)).toBe(true)
  })

  it('re-checking after TIMEOUT can return AVAILABLE if Commerce recovers', () => {
    const timeoutState = errorToPosCheckState(
      new DOMException('timeout', 'AbortError'),
    )
    expect(timeoutState.kind).toBe('TIMEOUT')

    const afterRetry = apiResponseToPosCheckState({
      available:      true,
      reserved_until: null,
      reservation_id: null,
    })
    expect(afterRetry.kind).toBe('AVAILABLE')
  })
})

// ── F7 — Zero invoice creation before positive availability ──────────────────
// "No invoice creation before a successful availability check."
// The component enforces this by only calling onConfirm when posCheckCanProceed.
// These tests prove the gate function is exhaustive across all states.

describe('F7: zero invoice creation before positive availability', () => {
  const blocking: PosCheckState[] = [
    { kind: 'IDLE' },
    { kind: 'CHECKING' },
    { kind: 'RESERVED', reservedUntil: '2026-07-20T10:00:00Z', reservationId: 'R' },
  ]

  const allowing: PosCheckState[] = [
    { kind: 'AVAILABLE' },
    { kind: 'TIMEOUT' },
    { kind: 'UNREACHABLE' },
  ]

  it.each(blocking)('$kind → canProceed=false (onConfirm must not fire)', (state) => {
    expect(posCheckCanProceed(state)).toBe(false)
  })

  it.each(allowing)('$kind → canProceed=true (onConfirm may fire)', (state) => {
    expect(posCheckCanProceed(state)).toBe(true)
  })
})

// ── F8 — Correct UX message for every domain state ───────────────────────────
// Proved by STATE_STORY_REGISTRY gate (state-coverage.test.ts):
//   6 stories (Idle, Checking, Available, Reserved, Timeout, Unreachable) each
//   render the corresponding COPY.pos.* message from contract-copy.ts.
// Structural smoke: COPY.pos messages exist and are non-empty strings.

describe('F8: correct UX message for every domain state', () => {
  it('COPY.pos contains all required state messages', async () => {
    const { COPY } = await import('@/lib/contract-copy')
    const pos = COPY.pos
    expect(typeof pos.idle).toBe('string')
    expect(typeof pos.checking).toBe('string')
    expect(typeof pos.available).toBe('string')
    expect(typeof pos.reserved).toBe('string')
    expect(typeof pos.timeout).toBe('string')
    expect(typeof pos.unreachable).toBe('string')
    // All non-empty
    for (const [key, val] of Object.entries(pos)) {
      if (typeof val === 'string') {
        expect(val.length, `COPY.pos.${key} is empty`).toBeGreaterThan(0)
      }
    }
  })

  it('reservedUntil is a function that formats the timestamp', async () => {
    const { COPY } = await import('@/lib/contract-copy')
    const msg = COPY.pos.reservedUntil('2026-07-19T15:00:00+03:00')
    expect(typeof msg).toBe('string')
    expect(msg).toContain('2026-07-19T15:00:00+03:00')
  })
})
