'use client'

/**
 * Owns the PricingCard state machine for the product page.
 * Reads goldStatus + age from GoldPriceContext (single source, FC-6).
 * Contract:
 *   - FRESH  → reserve button active → POST /reservations → RESERVED
 *   - STALE  → button disabled, stale copy shown
 *   - HALTED → button disabled, halted copy shown
 * No state in which the button looks active and does nothing (P0.1).
 */
import { useState, useCallback } from 'react'
import { useGoldPrice } from '@/lib/gold-price-context'
import { GoldPriceStatus } from '@/lib/domain-states'
import { reservationApi } from '@/lib/api'
import { PricingCard, type PricingState } from '@/components/pricing'
import type { BreakdownLine } from '@/components/pricing/GoldBreakdown'

interface Props {
  itemId:         string
  price:          number
  breakdownItems: BreakdownLine[]
}

type ReservationSlot =
  | { phase: 'idle' }
  | { phase: 'reserved'; lockedPrice: number; expiresAt: string }
  | { phase: 'expired' }

export function ProductPageClient({ itemId, price, breakdownItems }: Props) {
  const { age, status } = useGoldPrice()
  const [slot, setSlot] = useState<ReservationSlot>({ phase: 'idle' })

  const pricingState: PricingState =
    slot.phase === 'reserved' ? 'RESERVED'  :
    slot.phase === 'expired'  ? 'EXPIRED'   :
    status === GoldPriceStatus.HALTED        ? 'HALTED'   :
    status === GoldPriceStatus.STALE         ? 'STALE'    :
    'DEFAULT'

  const handleReserve = useCallback(async () => {
    if (status !== GoldPriceStatus.FRESH) return
    try {
      const res = await reservationApi.create(itemId)
      setSlot({ phase: 'reserved', lockedPrice: res.lockedPrice, expiresAt: res.expiresAt })
    } catch {
      // Race conflict or item unavailable — stay on DEFAULT so user sees fresh state
    }
  }, [itemId, status])

  const handleCancel = useCallback(() => {
    setSlot({ phase: 'idle' })
  }, [])

  const displayPrice = slot.phase === 'reserved' ? slot.lockedPrice : price
  const ms = slot.phase === 'reserved'
    ? Math.max(0, new Date(slot.expiresAt).getTime() - Date.now())
    : 0

  return (
    <PricingCard
      state={pricingState}
      price={displayPrice}
      ms={ms}
      goldStatus={status}
      ageSeconds={age}
      breakdownItems={breakdownItems}
      onReserve={handleReserve}
      onCancel={handleCancel}
      onReserveNew={() => setSlot({ phase: 'idle' })}
    />
  )
}
