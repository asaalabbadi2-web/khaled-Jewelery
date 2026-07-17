import { GoldPriceStatus } from '@/lib/domain-states'
import { COPY } from '@/lib/contract-copy'

export interface LiveStatusProps {
  status: GoldPriceStatus
  /** Required when status is FRESH — seconds since last update */
  ageSeconds?: number
}

export function LiveStatus({ status, ageSeconds }: LiveStatusProps) {
  if (status === GoldPriceStatus.FRESH) {
    return (
      <div className="flex items-center gap-1.5 mb-5">
        <span className="w-1.5 h-1.5 rounded-full bg-success animate-pulse shrink-0" aria-hidden="true" />
        <span className="text-muted text-xs">{COPY.goldBar.lastUpdatedPrefix}</span>
        <span dir="ltr" className="tabular-nums text-muted text-xs">{ageSeconds}</span>
        <span className="text-muted text-xs">{COPY.goldBar.lastUpdatedSuffix}</span>
      </div>
    )
  }

  if (status === GoldPriceStatus.HALTED) {
    return (
      <div className="flex items-start gap-2 bg-warning/[0.06] border border-warning/25 rounded-sm px-3 py-3 mb-5">
        <span className="w-1.5 h-1.5 rounded-full bg-warning mt-1.5 shrink-0" aria-hidden="true" />
        <p className="text-warning text-xs leading-relaxed">
          {COPY.goldBar.halted}
        </p>
      </div>
    )
  }

  // STALE
  return (
    <div className="flex items-center gap-2 bg-warning/[0.06] border border-warning/25 rounded-sm px-3 py-2 mb-5">
      <span className="w-1.5 h-1.5 rounded-full bg-warning animate-pulse shrink-0" aria-hidden="true" />
      <span className="text-warning text-xs">
        {COPY.pricing.staleUpdating}
      </span>
    </div>
  )
}
