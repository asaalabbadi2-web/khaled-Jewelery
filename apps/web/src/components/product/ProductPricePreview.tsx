import { pr } from '@/lib/format'

export interface ProductPricePreviewProps {
  price: number
  /** When provided, renders an amber stale-price timestamp label */
  stalePriceLabel?: string
}

export function ProductPricePreview({ price, stalePriceLabel }: ProductPricePreviewProps) {
  return (
    <div className="flex items-baseline justify-between mt-1.5">
      <span className="text-charcoal text-sm font-semibold">
        <span dir="ltr" className="tabular-nums">{pr(price)}</span>
        {' '}
        <span className="text-muted font-normal text-xs">ر.س</span>
      </span>
      {stalePriceLabel && (
        <span className="text-warning text-[10px]">{stalePriceLabel}</span>
      )}
    </div>
  )
}
