import { pr } from '@/lib/format'
import { COPY } from '@/lib/contract-copy'

export interface PriceHeaderProps {
  price: number
  /** Dims the price when rates are STALE */
  dimmed?: boolean
}

export function PriceHeader({ price, dimmed = false }: PriceHeaderProps) {
  return (
    <>
      <p className="text-muted text-[10px] font-semibold tracking-[0.12em] uppercase mb-1.5">
        {COPY.pricing.priceLabel}
      </p>
      <div className="flex items-baseline gap-2 mb-3">
        <span
          dir="ltr"
          className={`text-4xl font-semibold tabular-nums transition-opacity ${dimmed ? 'opacity-50 text-charcoal' : 'text-charcoal'}`}
        >
          {pr(price)}
        </span>
        <span className={`text-base ${dimmed ? 'text-muted/50' : 'text-muted'}`}>
          {COPY.pricing.priceUnit}
        </span>
      </div>
    </>
  )
}
