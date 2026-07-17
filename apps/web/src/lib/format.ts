/**
 * FC rule: numbers are always LTR tabular in RTL layouts.
 * Call pr() for all monetary values; wrap the result in dir="ltr" tabular-nums.
 */

/** Format a price with 2 decimal places, Latin numerals. */
export const pr = (n: number): string =>
  n.toLocaleString('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** Format a price as whole number (no decimals) — used in product cards. */
export const prCard = (n: number): string =>
  Math.round(n).toLocaleString('en')
