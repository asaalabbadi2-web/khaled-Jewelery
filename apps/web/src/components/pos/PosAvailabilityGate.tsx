'use client'

/**
 * Gate B Frontend — POS availability check component.
 *
 * Flow (mirrors the backend Gate B check in backend/services/commerce_availability.py):
 *   Operator selects item → auto-fetch GET /catalog/items/{id}/availability
 *   → POS renders domain state → sale may proceed only when check is non-blocking.
 *
 * Non-negotiables (from Sprint 10 brief):
 *   • No duplicated business rules — availability is evaluated by Commerce, not locally.
 *   • No cached availability used for confirmation — every confirmation path re-validates.
 *   • Fail-open policy mirrors backend: TIMEOUT / UNREACHABLE → allow with warning.
 *   • onConfirm is only callable when posCheckCanProceed(state) is true.
 *
 * Two exports:
 *   PosAvailabilityGate         — dumb renderer; takes explicit PosCheckState prop.
 *                                  Used by Storybook and tests.
 *   PosAvailabilityGateConnected — smart wrapper; fetches state from Commerce API.
 *                                  Used in operator-facing pages.
 *
 * Pure helpers (exported for unit tests — no rendering required):
 *   posCheckCanProceed          — maps state to proceed/block boolean.
 *   apiResponseToPosCheckState  — maps ItemAvailabilityResponse to PosCheckState.
 *   errorToPosCheckState        — maps fetch errors to TIMEOUT / UNREACHABLE.
 */

import { COPY } from '@/lib/contract-copy'
import {
  type PosCheckState,
  posCheckCanProceed,
  apiResponseToPosCheckState,
  errorToPosCheckState,
  usePosAvailability,
} from '@/lib/pos-availability'

// Re-export so test/story imports from this file continue to work unchanged.
export type { PosCheckState }
export { posCheckCanProceed, apiResponseToPosCheckState, errorToPosCheckState }

// ── Dumb renderer ─────────────────────────────────────────────────────────────

interface PosAvailabilityGateProps {
  state:     PosCheckState
  onCheck:   () => void
  onConfirm: () => void
}

export function PosAvailabilityGate({
  state,
  onCheck,
  onConfirm,
}: PosAvailabilityGateProps) {
  const copy = COPY.pos

  return (
    <div
      dir="rtl"
      className="rounded border p-4 text-sm"
      role="region"
      aria-label="فحص توفر القطعة"
    >
      {state.kind === 'IDLE' && (
        <div className="flex flex-col gap-3">
          <p className="text-[#7A7570]">{copy.idle}</p>
          <button
            type="button"
            onClick={onCheck}
            className="self-start bg-[#8C6F4E] text-white px-4 py-2 rounded text-sm font-medium hover:bg-[#7A5F40] transition-colors"
          >
            {copy.checkCta}
          </button>
        </div>
      )}

      {state.kind === 'CHECKING' && (
        <p
          className="text-[#7A7570] animate-pulse"
          aria-live="polite"
          aria-busy="true"
        >
          {copy.checking}
        </p>
      )}

      {state.kind === 'AVAILABLE' && (
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <span
              className="w-2 h-2 rounded-full bg-green-600 flex-shrink-0"
              aria-hidden="true"
            />
            <p className="text-green-700 font-medium">{copy.available}</p>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onConfirm}
              className="bg-[#8C6F4E] text-white px-4 py-2 rounded text-sm font-medium hover:bg-[#7A5F40] transition-colors"
            >
              {copy.confirmCta}
            </button>
            <button
              type="button"
              onClick={onCheck}
              className="border border-[#C9A96A]/40 text-[#8C6F4E] px-4 py-2 rounded text-sm hover:bg-[#F7F4EE] transition-colors"
            >
              {copy.retryCta}
            </button>
          </div>
        </div>
      )}

      {state.kind === 'RESERVED' && (
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <span
              className="w-2 h-2 rounded-full bg-red-500 flex-shrink-0"
              aria-hidden="true"
            />
            <p className="text-red-700 font-medium">{copy.reserved}</p>
          </div>
          <p className="text-[#7A7570] text-xs tabular-nums" dir="ltr">
            {copy.reservedUntil(state.reservedUntil)}
          </p>
          <button
            type="button"
            onClick={onCheck}
            className="self-start border border-[#C9A96A]/40 text-[#8C6F4E] px-4 py-2 rounded text-sm hover:bg-[#F7F4EE] transition-colors"
          >
            {copy.retryCta}
          </button>
          {/* Confirm button deliberately absent — sale is blocked until reservation expires */}
        </div>
      )}

      {(state.kind === 'TIMEOUT' || state.kind === 'UNREACHABLE') && (
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <span
              className="w-2 h-2 rounded-full bg-amber-500 flex-shrink-0"
              aria-hidden="true"
            />
            <p className="text-amber-700 font-medium">
              {state.kind === 'TIMEOUT' ? copy.timeout : copy.unreachable}
            </p>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onConfirm}
              className="border border-amber-400 text-amber-700 px-4 py-2 rounded text-sm hover:bg-amber-50 transition-colors"
            >
              {copy.proceedCta}
            </button>
            <button
              type="button"
              onClick={onCheck}
              className="border border-[#C9A96A]/40 text-[#8C6F4E] px-4 py-2 rounded text-sm hover:bg-[#F7F4EE] transition-colors"
            >
              {copy.retryCta}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Connected variant ─────────────────────────────────────────────────────────

interface PosAvailabilityGateConnectedProps {
  itemId:    number | null
  onConfirm: () => void
}

/**
 * Smart wrapper: auto-fetches Commerce availability when itemId changes.
 * Delegates fetch + state to usePosAvailability (lib/pos-availability.ts).
 */
export function PosAvailabilityGateConnected({
  itemId,
  onConfirm,
}: PosAvailabilityGateConnectedProps) {
  const { state, runCheck } = usePosAvailability(itemId)

  return (
    <PosAvailabilityGate
      state={state}
      onCheck={runCheck}
      onConfirm={onConfirm}
    />
  )
}
