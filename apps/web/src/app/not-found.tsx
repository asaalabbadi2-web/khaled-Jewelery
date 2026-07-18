import Link from 'next/link'
import { GoldPriceProvider } from '@/lib/gold-price-context'
import { GoldLiveBarWrapper } from '@/components/GoldLiveBarWrapper'
import { SiteNavWrapper } from '@/components/SiteNavWrapper'
import { ContentOffset } from '@/components/ContentOffset'
import { SiteFooter } from '@/components/SiteFooter'
import { COPY } from '@/lib/contract-copy'

export default function NotFound() {
  return (
    <GoldPriceProvider initialRates={null} initialAge={0}>
      <GoldLiveBarWrapper />
      <SiteNavWrapper />

      <ContentOffset>
        <main className="flex flex-col items-center justify-center min-h-[60vh] px-4 text-center pb-16">
          <p className="text-gold text-4xl mb-4" aria-hidden="true">
            {COPY.notFound.notFoundGlyph}
          </p>
          <h1 className="text-charcoal text-xl font-semibold mb-3">
            {COPY.notFound.title}
          </h1>
          <p className="text-muted text-sm leading-relaxed max-w-sm mb-8">
            {COPY.notFound.sub}
          </p>
          <div className="flex flex-wrap gap-3 justify-center">
            <Link
              href="/jewellery/rings"
              className="bg-bronze text-surface py-3 px-6 rounded-sm text-sm font-semibold hover:bg-bronze-hover transition-colors"
            >
              {COPY.notFound.browseCta}
            </Link>
            <Link
              href="/track"
              className="border border-gold/30 text-muted py-3 px-5 rounded-sm text-sm hover:border-gold/50 transition-colors"
            >
              {COPY.notFound.trackCta}
            </Link>
            <Link
              href="/"
              className="border border-gold/30 text-muted py-3 px-5 rounded-sm text-sm hover:border-gold/50 transition-colors"
            >
              {COPY.notFound.homeCta}
            </Link>
          </div>
        </main>
      </ContentOffset>

      <SiteFooter />
    </GoldPriceProvider>
  )
}
