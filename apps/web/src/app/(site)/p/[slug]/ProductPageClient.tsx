'use client'

/**
 * Owns the PricingCard state machine for the product page.
 * Reads goldStatus + age from GoldPriceContext (single source, FC-6).
 * Reads/writes ReservationContext so the BrowsingStripIsland knows when a
 * reservation is active across client-side navigation.
 *
 * v1.2 cap: at most 1 active reservation per session (ADR-022 R4 with cap=1).
 * Phase 2 will raise the cap to 3 via config — no code change here.
 */
import { useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { useGoldPrice } from '@/lib/gold-price-context'
import { useReservation } from '@/lib/reservation-context'
import { GoldPriceStatus } from '@/lib/domain-states'
import { reservationApi } from '@/lib/api'
import { serverNow } from '@/lib/server-clock'
import { COPY } from '@/lib/contract-copy'
import { PricingCard, type PricingState } from '@/components/pricing'
import type { BreakdownLine } from '@/components/pricing/GoldBreakdown'

interface Props {
  itemId:         string
  itemName:       string
  price:          number
  breakdownItems: BreakdownLine[]
}

type ReservationSlot =
  | { phase: 'idle' }
  | { phase: 'reserved'; reservationId: string; lockedPrice: number; expiresAt: string }
  | { phase: 'expired' }

export function ProductPageClient({ itemId, itemName, price, breakdownItems }: Props) {
  const router = useRouter()
  const { age, status } = useGoldPrice()
  const { reservations, addReservation, removeReservation } = useReservation()
  const [slot,   setSlot]   = useState<ReservationSlot>({ phase: 'idle' })
  const [capHit, setCapHit] = useState(false)

  const pricingState: PricingState =
    slot.phase === 'reserved' ? 'RESERVED'  :
    slot.phase === 'expired'  ? 'EXPIRED'   :
    status === GoldPriceStatus.HALTED        ? 'HALTED'   :
    status === GoldPriceStatus.STALE         ? 'STALE'    :
    'DEFAULT'

  const handleReserve = useCallback(async () => {
    if (status !== GoldPriceStatus.FRESH) return
    // v1.2 cap = 1 active reservation (ADR-022 R4)
    if (reservations.length > 0) {
      setCapHit(true)
      return
    }
    setCapHit(false)
    try {
      const res = await reservationApi.create(itemId)
      addReservation({ reservationId: res.reservationId, expiresAt: res.expiresAt })
      setSlot({
        phase: 'reserved',
        reservationId: res.reservationId,
        lockedPrice:   res.lockedPrice,
        expiresAt:     res.expiresAt,
      })
    } catch {
      // Race conflict or item unavailable — stay on DEFAULT so user sees fresh state
    }
  }, [itemId, status, reservations, addReservation])

  const handleCancel = useCallback(() => {
    if (slot.phase === 'reserved') removeReservation(slot.reservationId)
    setSlot({ phase: 'idle' })
    setCapHit(false)
  }, [slot, removeReservation])

  const handleReserveNew = useCallback(() => {
    if (slot.phase === 'reserved') removeReservation(slot.reservationId)
    setSlot({ phase: 'idle' })
    setCapHit(false)
  }, [slot, removeReservation])

  const handleCheckout = useCallback(() => {
    if (slot.phase !== 'reserved') return
    router.push(`/checkout?rid=${slot.reservationId}`)
  }, [slot, router])

  const handleAddAnother = useCallback(() => {
    router.push('/jewellery/rings')
  }, [router])

  const displayPrice = slot.phase === 'reserved' ? slot.lockedPrice : price
  const ms = slot.phase === 'reserved'
    ? Math.max(0, new Date(slot.expiresAt).getTime() - serverNow())
    : 0

  return (
    <PricingCard
      state={pricingState}
      price={displayPrice}
      ms={ms}
      goldStatus={status}
      ageSeconds={age}
      breakdownItems={breakdownItems}
      reserveCapMsg={capHit ? COPY.product.singleCapMsg : undefined}
      onReserve={handleReserve}
      onCancel={handleCancel}
      onReserveNew={handleReserveNew}
      onCheckout={handleCheckout}
      onAddAnother={handleAddAnother}
    />
  )
}
