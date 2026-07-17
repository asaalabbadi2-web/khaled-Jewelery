'use client'

import { cntFmt } from '@/lib/server-clock'
import { COPY } from '@/lib/contract-copy'

export interface ReservationStripProps {
  /** Remaining reservation milliseconds */
  ms: number
  /** Full reservation window — used to compute depleting bar percentage */
  reservationMs: number
  /** True when network is down and the counter is paused */
  frozen?: boolean
}

export function ReservationStrip({ ms, reservationMs, frozen = false }: ReservationStripProps) {
  const amber  = !frozen && ms <= 60_000
  const barPct = Math.max(0, Math.min(100, (ms / reservationMs) * 100))

  return (
    <div className="fixed top-10 inset-x-0 z-40 bg-charcoal" aria-label={COPY.reservationStrip.label}>
      <div className="h-11 flex items-center justify-center gap-2 px-4 text-xs">
        <span className="text-muted">{COPY.reservationStrip.message}</span>
        <span
          dir="ltr"
          className={`tabular-nums font-semibold ${amber ? 'text-warning' : 'text-ivory/90'}`}
          aria-label={`الوقت المتبقي ${cntFmt(ms)}`}
        >
          {cntFmt(ms)}
        </span>
        {frozen && (
          <span className="text-muted-2 text-[10px] border border-muted-2/40 px-1.5 py-0.5 rounded-sm">
            {COPY.reservationStrip.frozen}
          </span>
        )}
      </div>

      {/* Depleting gold bar */}
      <div className="h-px bg-gold/[0.12] relative overflow-hidden">
        <div
          className={`absolute inset-y-0 right-0 transition-[width] duration-1000 opacity-50 ${amber ? 'bg-warning' : 'bg-gold'}`}
          style={{ width: `${barPct}%` }}
          aria-hidden="true"
        />
      </div>
    </div>
  )
}
