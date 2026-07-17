import Link from 'next/link'
import { TrendingUp, Gem, Award, Package } from 'lucide-react'
import { ProductCard } from '@/components/product'
import { ItemAvailability } from '@/lib/domain-states'
import { COPY } from '@/lib/contract-copy'

const FEATURED = [
  { id: 'R-21-0342', name: 'خاتم سوليتير',  karat: 21 as const, weight: 8.45,  price: 1_215, availability: ItemAvailability.AVAILABLE, img: 'https://images.unsplash.com/photo-1605100804763-247f67b3557e?w=600&h=600&fit=crop&auto=format' },
  { id: 'R-21-0418', name: 'خاتم تريلوجي',  karat: 21 as const, weight: 9.30,  price: 2_340, availability: ItemAvailability.RESERVED,  img: 'https://images.unsplash.com/photo-1589128777073-263566ae5e4d?w=600&h=600&fit=crop&auto=format' },
  { id: 'R-18-0314', name: 'خاتم هالو',      karat: 18 as const, weight: 5.60,  price: 1_480, availability: ItemAvailability.AVAILABLE, img: 'https://images.unsplash.com/photo-1598560917807-1bae44bd2be8?w=600&h=600&fit=crop&auto=format' },
  { id: 'R-21-0385', name: 'خاتم بافلي',     karat: 21 as const, weight: 7.20,  price: 1_651, availability: ItemAvailability.AVAILABLE, img: 'https://images.unsplash.com/photo-1611955167811-4711904bb9f8?w=600&h=600&fit=crop&auto=format' },
  { id: 'R-21-0466', name: 'خاتم فينيتاج',   karat: 21 as const, weight: 11.80, price: 3_050, availability: ItemAvailability.AVAILABLE, img: 'https://images.unsplash.com/photo-1602173574767-37ac01994b2a?w=600&h=600&fit=crop&auto=format' },
  { id: 'R-21-0399', name: 'خاتم كلاسيك',    karat: 21 as const, weight: 7.80,  price: 1_790, availability: ItemAvailability.AVAILABLE, img: 'https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=600&h=600&fit=crop&auto=format' },
]

const COLLECTIONS = [
  {
    slug:  'rings',
    name:  COPY.home.colRings,
    sub:   COPY.home.colRingsSub,
    img:   'https://images.unsplash.com/photo-1605100804763-247f67b3557e?w=600&h=600&fit=crop&auto=format',
  },
  {
    slug:  'bracelets',
    name:  COPY.home.colBracelets,
    sub:   COPY.home.colBraceletsSub,
    img:   'https://images.unsplash.com/photo-1573408301185-9519f94816b5?w=600&h=600&fit=crop&auto=format',
  },
  {
    slug:  'necklaces',
    name:  COPY.home.colNecklaces,
    sub:   COPY.home.colNecklacesSub,
    img:   'https://images.unsplash.com/photo-1515562141207-7a88fb7ce338?w=600&h=600&fit=crop&auto=format',
  },
  {
    slug:  'sets',
    name:  COPY.home.colSets,
    sub:   COPY.home.colSetsSub,
    img:   'https://images.unsplash.com/photo-1611085583191-a3b181a88401?w=600&h=600&fit=crop&auto=format',
  },
]

const WHY_US = [
  { icon: TrendingUp, text: COPY.home.whyLivePrice,  sub: COPY.home.whyLivePriceSub },
  { icon: Gem,        text: COPY.home.whyUnique,      sub: COPY.home.whyUniqueSub    },
  { icon: Award,      text: COPY.home.whyCert,        sub: COPY.home.whyCertSub      },
  { icon: Package,    text: COPY.home.whyShipping,    sub: COPY.home.whyShippingSub  },
]

const HOW_IT_WORKS = [
  COPY.home.step1,
  COPY.home.step2,
  COPY.home.step3,
  COPY.home.step4,
]

const CHIPS = [
  COPY.home.chipLiveGold,
  COPY.home.chipInstant,
  COPY.home.chipSafe,
  COPY.home.chipShipping,
]

export default function HomePage() {
  return (
    <main>
      {/* ── HERO ── */}
      <section className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 pb-16">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 lg:gap-12 items-center">
          {/* Left: image */}
          <div
            className="relative overflow-hidden rounded-sm bg-image-bg order-1 lg:order-none"
            style={{ aspectRatio: '4/5' }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src="https://images.unsplash.com/photo-1605100804763-247f67b3557e?w=800&h=1000&fit=crop&auto=format"
              alt={COPY.home.heroImgAlt}
              className="w-full h-full object-cover mix-blend-multiply"
            />
          </div>

          {/* Right: copy */}
          <div className="flex flex-col gap-6 order-none lg:order-1">
            <h1 className="text-3xl sm:text-[2.25rem] font-semibold tracking-[-0.02em] text-charcoal leading-snug">
              {COPY.home.heroTitle}
            </h1>
            <p className="text-muted text-sm leading-relaxed max-w-sm">
              {COPY.home.heroSub}
            </p>

            {/* Trust chips */}
            <div className="flex flex-wrap gap-2">
              {CHIPS.map(chip => (
                <span
                  key={chip}
                  className="border border-gold/30 text-muted text-xs px-2.5 py-1 rounded-sm"
                >
                  {chip}
                </span>
              ))}
            </div>

            {/* CTAs */}
            <div className="flex flex-wrap gap-3">
              <Link
                href="/jewellery/rings"
                className="bg-bronze text-surface px-5 py-3 rounded-sm text-sm font-semibold hover:bg-bronze-hover transition-colors"
              >
                {COPY.home.browseCta}
              </Link>
              <Link
                href="/track"
                className="border border-gold/30 text-muted px-5 py-3 rounded-sm text-sm hover:border-gold/50 transition-colors"
              >
                {COPY.home.trackCta}
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* ── COLLECTIONS ── */}
      <section className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 pb-16">
        <h2 className="text-xl font-semibold text-charcoal tracking-[-0.02em] mb-6">
          {COPY.home.collectionsH2}
        </h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {COLLECTIONS.map(col => (
            <Link
              key={col.slug}
              href={`/jewellery/${col.slug}`}
              className="group relative overflow-hidden rounded-sm bg-image-bg"
              style={{ aspectRatio: '3/4' }}
              aria-label={COPY.productCard.browseCategory(col.name)}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={col.img}
                alt=""
                aria-hidden="true"
                className="absolute inset-0 w-full h-full object-cover mix-blend-multiply group-hover:scale-105 transition-transform duration-500"
              />
              <div className="absolute inset-0 bg-gradient-to-t from-charcoal/70 via-transparent to-transparent" />
              <div className="absolute bottom-0 inset-x-0 p-3">
                <p className="text-ivory font-semibold text-sm">{col.name}</p>
                <p className="text-ivory/60 text-xs mt-0.5">{col.sub}</p>
              </div>
            </Link>
          ))}
        </div>
      </section>

      {/* ── HOW IT WORKS ── */}
      <section className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 pb-16 border-t border-gold/15 pt-10">
        <h2 className="text-xl font-semibold text-charcoal tracking-[-0.02em] mb-8">
          {COPY.home.howItWorksH2}
        </h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-6">
          {HOW_IT_WORKS.map((step, i) => (
            <div key={step} className="flex flex-col gap-2">
              <span
                className="w-7 h-7 rounded-full border border-gold/40 grid place-items-center text-gold text-xs font-semibold"
                aria-hidden="true"
              >
                {i + 1}
              </span>
              <p className="text-charcoal text-sm font-medium leading-snug">{step}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── FEATURED ── */}
      <section
        className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 pb-16"
        aria-label={COPY.home.featuredH2}
      >
        <div className="flex items-baseline justify-between mb-6">
          <h2 className="text-xl font-semibold text-charcoal tracking-[-0.02em]">
            {COPY.home.featuredH2}
          </h2>
          <Link
            href="/jewellery/rings"
            className="text-xs text-muted hover:text-charcoal transition-colors"
          >
            {COPY.home.viewAllCta}
          </Link>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 sm:gap-5">
          {FEATURED.map(product => (
            <ProductCard key={product.id} product={product} />
          ))}
        </div>
      </section>

      {/* ── WHY-US ── */}
      <section className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 pb-16 border-t border-gold/15 pt-10">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-6">
          {WHY_US.map(({ icon: Icon, text, sub }) => (
            <div key={text} className="flex flex-col gap-2">
              <span className="text-gold"><Icon size={18} aria-hidden="true" /></span>
              <p className="text-charcoal text-sm font-medium leading-snug">{text}</p>
              <p className="text-muted text-xs leading-relaxed">{sub}</p>
            </div>
          ))}
        </div>
      </section>
    </main>
  )
}
