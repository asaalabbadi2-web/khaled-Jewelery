import { Suspense } from 'react'
import { GoldPriceProvider } from '@/lib/gold-price-context'
import { GoldLiveBarWrapper } from '@/components/GoldLiveBarWrapper'
import { SiteNavWrapper } from '@/components/SiteNavWrapper'
import { ContentOffset } from '@/components/ContentOffset'
import { SiteFooter } from '@/components/SiteFooter'
import { TrackPageClient } from './TrackPageClient'

// Tracking page lives outside (site) layout so it can control active nav state.
export default function TrackPage() {
  return (
    <GoldPriceProvider initialRates={null} initialAge={0}>
      <GoldLiveBarWrapper />
      <SiteNavWrapper />

      <ContentOffset>
        <main className="pb-16">
          <Suspense>
            <TrackPageClient />
          </Suspense>
        </main>
      </ContentOffset>

      <SiteFooter />
    </GoldPriceProvider>
  )
}
