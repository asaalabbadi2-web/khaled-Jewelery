'use client'

import { useState, useEffect } from 'react'
import { useReservation } from '@/lib/reservation-context'
import { useGoldPrice } from '@/lib/gold-price-context'
import { serverNow } from '@/lib/server-clock'
import { BrowsingReservationStrip } from '@/components/checkout/BrowsingReservationStrip'

export function BrowsingStripIsland() {
  const { reservations, removeReservation } = useReservation()
  const { hasBanner } = useGoldPrice()
  const [ms, setMs] = useState(0)

  useEffect(() => {
    if (reservations.length === 0) {
      setMs(0)
      return
    }

    const tick = () => {
      const now  = serverNow()
      // Remove any that have expired
      for (const r of reservations) {
        if (new Date(r.expiresAt).getTime() <= now) {
          removeReservation(r.reservationId)
        }
      }
      // Compute ms to earliest non-expired expiry
      const remaining = reservations
        .map(r => new Date(r.expiresAt).getTime() - now)
        .filter(t => t > 0)
      setMs(remaining.length > 0 ? Math.min(...remaining) : 0)
    }

    tick()
    const id = setInterval(tick, 1_000)
    return () => clearInterval(id)
  }, [reservations, removeReservation])

  const active = reservations.filter(
    r => new Date(r.expiresAt).getTime() > serverNow(),
  )

  if (active.length === 0 || ms <= 0) return null

  const checkoutHref = `/checkout?rid=${active[0].reservationId}`

  return (
    <BrowsingReservationStrip
      count={active.length}
      ms={ms}
      checkoutHref={checkoutHref}
      hasBanner={hasBanner}
    />
  )
}
