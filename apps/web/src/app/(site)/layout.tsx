import { goldApi } from '@/lib/api'
import { GoldPriceProvider } from '@/lib/gold-price-context'
import { GoldLiveBarWrapper } from '@/components/GoldLiveBarWrapper'
import { SiteNavWrapper } from '@/components/SiteNavWrapper'
import { ContentOffset } from '@/components/ContentOffset'
import { SiteFooter } from '@/components/SiteFooter'

export default async function SiteLayout({ children }: { children: React.ReactNode }) {
  let initialRates = null
  let initialAge   = 0

  try {
    const data = await goldApi.getRates()
    initialRates = { karat24: data.karat24, karat21: data.karat21 }
    initialAge   = Math.max(0, Math.floor((Date.now() - new Date(data.updatedAt).getTime()) / 1_000))
  } catch {
    // SSR fetch fails in dev (MSW is browser-only) — GoldPriceProvider re-fetches client-side
  }

  return (
    <GoldPriceProvider initialRates={initialRates} initialAge={initialAge}>
      <GoldLiveBarWrapper />
      <SiteNavWrapper />
      <ContentOffset>{children}</ContentOffset>
      <SiteFooter />
    </GoldPriceProvider>
  )
}
