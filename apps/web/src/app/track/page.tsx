import { GoldLiveBarWrapper } from '@/components/GoldLiveBarWrapper'
import { SiteNavWrapper } from '@/components/SiteNavWrapper'
import { SiteFooter } from '@/components/SiteFooter'
import { OtpInput } from '@/components/tracking/OtpInput'
import { goldApi } from '@/lib/api'
import { COPY } from '@/lib/contract-copy'

// Tracking page lives outside (site) layout so it can control active nav state.
export default async function TrackPage() {
  let rates = null
  let initialAge = 0

  try {
    const data = await goldApi.getRates()
    rates = { karat24: data.karat24, karat21: data.karat21 }
    initialAge = Math.max(0, Math.floor((Date.now() - new Date(data.updatedAt).getTime()) / 1_000))
  } catch { /* graceful degradation */ }

  return (
    <>
      <GoldLiveBarWrapper rates={rates} initialAge={initialAge} />
      <SiteNavWrapper hasBanner />

      <main className="pt-36 pb-16">
        <div className="max-w-[40rem] mx-auto px-4 sm:px-6">
          <section className="border border-gold/20 bg-surface rounded-sm p-5 sm:p-6">
            <h1 className="text-charcoal text-2xl font-semibold mb-6">
              {COPY.tracking.pageTitle}
            </h1>
            <label htmlFor="order-number" className="block text-xs font-medium text-charcoal mb-1.5">
              {COPY.tracking.orderNumberLabel}
            </label>
            <input
              id="order-number"
              dir="ltr"
              placeholder="ORD-5511"
              className="w-full border border-gold/30 bg-surface rounded-sm px-3 py-2.5 text-sm text-charcoal focus:outline-none focus:border-gold focus:ring-1 focus:ring-gold/30 tabular-nums"
            />
            <button className="w-full mt-4 bg-bronze text-surface py-3.5 rounded-sm text-sm font-semibold tracking-wide hover:bg-bronze-hover transition-colors">
              {COPY.tracking.sendOtpCta}
            </button>
            <p className="text-muted text-xs mt-3">{COPY.tracking.otpHint}</p>
          </section>
        </div>
      </main>

      <SiteFooter />
    </>
  )
}
