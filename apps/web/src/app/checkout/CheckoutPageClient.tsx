'use client'

import { useSearchParams } from 'next/navigation'
import { useGoldPrice } from '@/lib/gold-price-context'
import { ReservationStrip } from '@/components/checkout/ReservationStrip'
import { PricingCard } from '@/components/pricing'
import { RESERVATION_MS } from '@/lib/server-clock'

export function CheckoutPageClient() {
  const params     = useSearchParams()
  const expiresAt  = params.get('expiresAt') ?? ''
  const price      = parseFloat(params.get('price') ?? '0')

  // age tick from context drives re-render every second → ms updates continuously
  const { age: _age } = useGoldPrice()

  const ms = expiresAt
    ? Math.max(0, new Date(expiresAt).getTime() - Date.now())
    : 0

  return (
    <>
      <ReservationStrip ms={ms} reservationMs={RESERVATION_MS} />
      <main className="pt-48 max-w-2xl mx-auto px-4 sm:px-6 pb-16">
        <PricingCard state="RESERVED" price={price} ms={ms} />
      </main>
    </>
  )
}
