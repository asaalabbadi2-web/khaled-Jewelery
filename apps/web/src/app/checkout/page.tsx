import { Suspense } from 'react'
import { GoldPriceProvider } from '@/lib/gold-price-context'
import { GoldLiveBarWrapper } from '@/components/GoldLiveBarWrapper'
import { CheckoutPageClient } from './CheckoutPageClient'

// Checkout lives outside (site) layout — has its own minimal chrome.
export default function CheckoutPage() {
  return (
    <GoldPriceProvider initialRates={null} initialAge={0}>
      <GoldLiveBarWrapper />
      <Suspense>
        <CheckoutPageClient />
      </Suspense>
    </GoldPriceProvider>
  )
}
