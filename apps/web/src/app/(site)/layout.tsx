import { goldApi } from '@/lib/api'
import { GoldLiveBarWrapper } from '@/components/GoldLiveBarWrapper'
import { SiteNavWrapper } from '@/components/SiteNavWrapper'
import { SiteFooter } from '@/components/SiteFooter'

export default async function SiteLayout({ children }: { children: React.ReactNode }) {
  let rates = null
  let initialAge = 0

  try {
    const data = await goldApi.getRates()
    rates = { karat24: data.karat24, karat21: data.karat21 }
    initialAge = Math.max(0, Math.floor((Date.now() - new Date(data.updatedAt).getTime()) / 1_000))
  } catch {
    // rates stays null — GoldLiveBar hides price columns gracefully
  }

  return (
    <>
      <GoldLiveBarWrapper rates={rates} initialAge={initialAge} />
      <SiteNavWrapper hasBanner />
      {/* pt-36 accounts for fixed GoldLiveBar (h-10) + SiteHeader (h-16) + gap */}
      <div className="pt-36 min-h-screen">
        {children}
      </div>
      <SiteFooter />
    </>
  )
}
