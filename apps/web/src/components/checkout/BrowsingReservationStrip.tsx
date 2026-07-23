'use client'

import Link from 'next/link'
import { cntFmt } from '@/lib/server-clock'
import { COPY } from '@/lib/contract-copy'

export interface BrowsingReservationStripProps {
  /** Number of active reservations (Phase 2: may be > 1) */
  count:        number
  /** Milliseconds until the earliest reservation expires */
  ms:           number
  /** Where «إتمام الدفع» navigates */
  checkoutHref: string
  /** True when GoldLiveBar is showing — shifts the strip below the taller header */
  hasBanner?:   boolean
}

export function BrowsingReservationStrip({
  count,
  ms,
  checkoutHref,
  hasBanner = false,
}: BrowsingReservationStripProps) {
  const urgent = !!(ms && ms <= 60_000)
  const top    = hasBanner ? 'top-36' : 'top-[104px]'

  return (
    <div
      className={`fixed ${top} inset-x-0 z-30 bg-charcoal`}
      aria-label={COPY.browsingStrip.ariaLabel}
      dir="rtl"
    >
      <div className="h-10 flex items-center justify-center gap-3 px-4 text-xs">
        <span className="text-muted">
          {count > 1 ? COPY.browsingStrip.multi(count) : COPY.browsingStrip.single}
        </span>
        <span
          dir="ltr"
          className={`tabular-nums font-semibold ${urgent ? 'text-warning' : 'text-ivory/90'}`}
          aria-label={`الوقت المتبقي ${cntFmt(ms)}`}
        >
          {cntFmt(ms)}
        </span>
        <Link
          href={checkoutHref}
          className="text-gold text-xs font-medium hover:text-bronze transition-colors underline-offset-2 hover:underline"
        >
          {COPY.browsingStrip.checkoutLink}
        </Link>
      </div>
    </div>
  )
}
