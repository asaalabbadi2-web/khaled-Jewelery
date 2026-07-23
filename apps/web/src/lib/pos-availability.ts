'use client'

/**
 * POS availability domain: types, pure helpers, and the usePosAvailability hook.
 *
 * Lives in lib/ so it may import from lib/api.
 * Components import from here (or re-export via PosAvailabilityGate) —
 * they must never import lib/api directly (dep-cruiser: components-no-lib-api).
 */

import { useState, useCallback, useEffect } from 'react'
import { availabilityApi, type ItemAvailabilityResponse } from '@/lib/api'

// ── State discriminated union ─────────────────────────────────────────────────

export type PosCheckState =
  | { kind: 'IDLE' }
  | { kind: 'CHECKING' }
  | { kind: 'AVAILABLE' }
  | { kind: 'RESERVED'; reservedUntil: string; reservationId: string }
  | { kind: 'TIMEOUT' }
  | { kind: 'UNREACHABLE' }

// ── Pure helpers ──────────────────────────────────────────────────────────────

/**
 * True when the operator may proceed to invoice creation.
 * AVAILABLE → proceed; TIMEOUT / UNREACHABLE → proceed with warning (fail-open).
 * RESERVED / IDLE / CHECKING → block.
 */
export function posCheckCanProceed(state: PosCheckState): boolean {
  return (
    state.kind === 'AVAILABLE' ||
    state.kind === 'TIMEOUT' ||
    state.kind === 'UNREACHABLE'
  )
}

/**
 * Map a Commerce API availability response to a PosCheckState.
 * Business decision lives in Commerce — this is a pure projection.
 */
export function apiResponseToPosCheckState(
  r: ItemAvailabilityResponse,
): PosCheckState {
  if (r.available) return { kind: 'AVAILABLE' }
  return {
    kind:           'RESERVED',
    reservedUntil:  r.reserved_until ?? '',
    reservationId:  r.reservation_id ?? '',
  }
}

/**
 * Map a fetch / network error to a PosCheckState.
 * AbortError (5 s race) → TIMEOUT; all others → UNREACHABLE.
 */
export function errorToPosCheckState(err: unknown): PosCheckState {
  if (
    (err instanceof DOMException && err.name === 'AbortError') ||
    (err instanceof Error && err.name === 'AbortError')
  ) {
    return { kind: 'TIMEOUT' }
  }
  return { kind: 'UNREACHABLE' }
}

// ── Hook ──────────────────────────────────────────────────────────────────────

/**
 * Fetch availability from Commerce API and manage PosCheckState.
 * 5 s race enforces TIMEOUT (fail-open) on slow/unreachable responses.
 * H4 (ADR-016): UI budget is 5 s vs 2 s backend — UI is not on the write path
 * so a longer wait is safe; backend must not hold the DB session idle.
 */
export function usePosAvailability(itemId: number | null): {
  state:    PosCheckState
  runCheck: () => void
} {
  const [state, setState] = useState<PosCheckState>({ kind: 'IDLE' })

  const runCheck = useCallback(async () => {
    if (itemId === null) {
      setState({ kind: 'IDLE' })
      return
    }
    setState({ kind: 'CHECKING' })
    const timeout = new Promise<never>((_, reject) =>
      setTimeout(
        () => reject(new DOMException('Gate B timeout', 'AbortError')),
        5_000,
      ),
    )
    try {
      const result = await Promise.race([availabilityApi.check(itemId), timeout])
      setState(apiResponseToPosCheckState(result))
    } catch (err) {
      setState(errorToPosCheckState(err))
    }
  }, [itemId])

  useEffect(() => { void runCheck() }, [runCheck])

  return { state, runCheck }
}
