'use client'

import { cntFmt } from '@/lib/server-clock'
import { COPY } from '@/lib/contract-copy'

export interface CountdownBlockProps {
  /** Remaining milliseconds */
  ms: number
  /** Full reservation window in ms — used to compute the depleting bar */
  reservationMs: number
  /** When true, freezes the counter appearance (offline state) */
  frozen?: boolean
}

export function CountdownBlock({ ms, reservationMs, frozen = false }: CountdownBlockProps) {
  const amber   = !frozen && ms <= 60_000
  const pct     = Math.max(0, Math.min(100, (ms / reservationMs) * 100))
  const display = cntFmt(ms)

  return (
    <div className="flex flex-col items-center py-5 gap-1.5 bg-ivory rounded-sm mb-5">
      <span className="text-muted text-xs">{COPY.pricing.timeLabel}</span>
      <span
        dir="ltr"
        className={[
          'text-5xl font-bold tabular-nums tracking-tight transition-colors duration-700',
          frozen   ? 'text-charcoal opacity-35' :
          amber    ? 'text-warning' :
                     'text-charcoal',
        ].join(' ')}
        role="timer"
        aria-label={frozen
          ? COPY.pricing.cancelledFrozen
          : `الوقت المتبقي ${display}`
        }
      >
        {display}
      </span>

      {/* Depleting bar */}
      <div
        className="relative h-1 w-full max-w-[13rem] overflow-hidden rounded-full bg-skeleton"
        dir="rtl"
        aria-hidden="true"
      >
        <div
          className={[
            'absolute inset-y-0 right-0 h-full rounded-full transition-[width,background-color] duration-700',
            frozen ? 'bg-charcoal/35' :
            amber  ? 'bg-warning' :
                     'bg-charcoal',
          ].join(' ')}
          style={{ width: `${pct}%` }}
        />
      </div>

      {amber && (
        <span className="text-warning text-xs mt-0.5" role="alert">
          {COPY.pricing.urgentWarning}
        </span>
      )}
    </div>
  )
}
