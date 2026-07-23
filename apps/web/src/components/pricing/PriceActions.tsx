'use client'

import { COPY } from '@/lib/contract-copy'
import { Button } from '@/components/ui'

export type PriceActionsVariant =
  | 'reserve'
  | 'checkout'
  | 'browse'
  | 'reserve-new'
  | 'disabled-stale'
  | 'disabled-halted'
  | 'disabled-checkout'

export interface PriceActionsProps {
  variant: PriceActionsVariant
  onReserve?(): void
  onCancel?(): void
  onReserveNew?(): void
  onCheckout?(): void
  onBrowse?(): void
  /** v1.2: returns to catalog with strip visible; Phase 2: opens basket */
  onAddAnother?(): void
}

export function PriceActions({
  variant,
  onReserve,
  onCancel,
  onReserveNew,
  onCheckout,
  onBrowse,
  onAddAnother,
}: PriceActionsProps) {
  if (variant === 'reserve') {
    return (
      <>
        <Button variant="bronze" className="w-full" onClick={onReserve}>
          {COPY.pricing.reserveCta}
        </Button>
        <p className="text-center text-muted text-xs mt-2.5 leading-relaxed">
          {COPY.pricing.reserveNote}
        </p>
      </>
    )
  }

  if (variant === 'checkout') {
    return (
      <>
        <Button variant="bronze" className="w-full mb-3" onClick={onCheckout}>
          {COPY.pricing.checkoutCta}
        </Button>
        {onAddAnother && (
          <div className="text-center mb-2">
            <button
              onClick={onAddAnother}
              className="text-muted text-xs underline underline-offset-2 hover:text-charcoal transition-colors"
            >
              {COPY.product.addAnother}
            </button>
          </div>
        )}
        <div className="text-center mb-3">
          <button
            onClick={onCancel}
            className="text-muted text-xs underline underline-offset-2 hover:text-charcoal transition-colors"
          >
            {COPY.pricing.cancelLink}
          </button>
        </div>
        <p className="text-center text-muted text-xs leading-relaxed">
          {COPY.pricing.reservedExclusive}
        </p>
      </>
    )
  }

  if (variant === 'reserve-new') {
    return (
      <>
        <Button variant="bronze" className="w-full mb-2" onClick={onReserveNew}>
          {COPY.pricing.reserveNewCta}
        </Button>
        <Button variant="outline" className="w-full" onClick={onCancel}>
          إلغاء
        </Button>
      </>
    )
  }

  if (variant === 'browse') {
    return (
      <Button variant="outline" className="w-full" onClick={onBrowse}>
        {COPY.pricing.browseSimilar}
      </Button>
    )
  }

  if (variant === 'disabled-stale') {
    return (
      <Button variant="bronze" className="w-full" disabled aria-disabled="true">
        {COPY.pricing.staleUpdating}
      </Button>
    )
  }

  if (variant === 'disabled-halted') {
    return (
      <Button variant="bronze" className="w-full" disabled aria-disabled="true">
        {COPY.goldBar.halted}
      </Button>
    )
  }

  // disabled-checkout (OFFLINE state)
  return (
    <Button variant="bronze" className="w-full" disabled aria-disabled="true">
      {COPY.pricing.checkoutCta}
    </Button>
  )
}
