import { GoldPriceProvider } from '@/lib/gold-price-context'
import { GoldLiveBarWrapper } from '@/components/GoldLiveBarWrapper'
import { ReservationStrip } from '@/components/checkout/ReservationStrip'
import { PricingCard } from '@/components/pricing'
import { RESERVATION_MS } from '@/lib/server-clock'

// Checkout lives outside (site) layout — has its own minimal chrome.
export default function CheckoutPage() {
  const mockMs = 7 * 60_000 + 30_000

  return (
    <GoldPriceProvider initialRates={null} initialAge={0}>
      <GoldLiveBarWrapper />
      <ReservationStrip ms={mockMs} reservationMs={RESERVATION_MS} />

      {/* pt-48: GoldLiveBar (h-10) + ReservationStrip (~h-12) + SiteHeader (h-16) */}
      <main className="pt-48 max-w-2xl mx-auto px-4 sm:px-6 pb-16">
        <PricingCard
          state="RESERVED"
          price={1_214.69}
          ms={mockMs}
        />
      </main>
    </GoldPriceProvider>
  )
}
