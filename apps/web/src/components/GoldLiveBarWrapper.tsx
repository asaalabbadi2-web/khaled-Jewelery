'use client'

import { GoldLiveBar } from './GoldLiveBar'
import { useGoldPrice } from '@/lib/gold-price-context'
import { GoldPriceStatus } from '@/lib/domain-states'
import { COPY } from '@/lib/contract-copy'

/** Reads from GoldPriceContext (single source). Renders bar + HALTED banner when active. */
export function GoldLiveBarWrapper() {
  const { rates, age, status } = useGoldPrice()
  const halted = status === GoldPriceStatus.HALTED

  return (
    <>
      <GoldLiveBar age={age} halted={halted} rates={rates} />
      {halted && (
        <div
          role="alert"
          className="fixed top-10 inset-x-0 h-10 z-40 bg-warning/[0.08] border-b border-warning/20 flex items-center justify-center px-4"
        >
          <span className="text-warning text-xs text-center">{COPY.banners.halted}</span>
        </div>
      )}
    </>
  )
}
