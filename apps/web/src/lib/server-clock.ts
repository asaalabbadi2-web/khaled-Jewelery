/**
 * FC-2 — Server Time Only.
 * Device clock is never trusted for business timing.
 * All timers derive from server-anchored time.
 */

// ─── Factory (testable, one clock per use-case) ───────────────
export interface ServerClock {
  /** Current time corrected for device clock skew. */
  now(): Date
  /** Re-sync offset when a new server timestamp arrives. */
  update(serverNowIso: string): void
}

export function createServerClock(serverNowIso: string): ServerClock {
  // offset = server_time − device_time.  Positive when device is behind.
  let offset = new Date(serverNowIso).getTime() - Date.now()
  return {
    now() { return new Date(Date.now() + offset) },
    update(iso: string) { offset = new Date(iso).getTime() - Date.now() },
  }
}

// ─── Module singleton (convenience for client components / countdown hooks) ─
// Synced from API response headers (Date or server_now field).
let _moduleOffset = 0

/** Re-anchor the module singleton from a server ISO timestamp. */
export const syncServerClock = (serverNowIso: string) => {
  _moduleOffset = new Date(serverNowIso).getTime() - Date.now()
}

/** Current server time as epoch-ms, corrected for device clock skew. */
export const serverNow = (): number => Date.now() + _moduleOffset

// ─── Shared constants ────────────────────────────────────────
/** Reservation window in milliseconds (10 min). */
export const RESERVATION_MS = 10 * 60 * 1_000

/**
 * Format remaining milliseconds as "mm:ss" — used in countdown UI.
 * Negative values clamp to "00:00".
 */
export function cntFmt(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1_000))
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}
