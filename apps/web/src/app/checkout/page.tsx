import { GoldLiveBarWrapper } from '@/components/GoldLiveBarWrapper'
import { ReservationStrip } from '@/components/checkout/ReservationStrip'
import { PricingCard } from '@/components/pricing'
import { RESERVATION_MS } from '@/lib/server-clock'
import { goldApi } from '@/lib/api'

// Checkout lives outside (site) layout — has its own minimal chrome.
export default async function CheckoutPage() {
  let rates = null
  let initialAge = 0

  try {
    const data = await goldApi.getRates()
    rates = { karat24: data.karat24, karat21: data.karat21 }
    initialAge = Math.max(0, Math.floor((Date.now() - new Date(data.updatedAt).getTime()) / 1_000))
  } catch { /* graceful degradation */ }

  const mockMs = 7 * 60_000 + 30_000

  return (
    <>
      <GoldLiveBarWrapper rates={rates} initialAge={initialAge} />
      <ReservationStrip ms={mockMs} reservationMs={RESERVATION_MS} />

      {/* pt-48: GoldLiveBar (h-10) + ReservationStrip (~h-12) + SiteHeader (h-16) */}
      <main className="pt-48 max-w-2xl mx-auto px-4 sm:px-6 pb-16">
        <PricingCard
          state="RESERVED"
          price={1_214.69}
          ms={mockMs}
        />
      </main>
    </>
  )
}
