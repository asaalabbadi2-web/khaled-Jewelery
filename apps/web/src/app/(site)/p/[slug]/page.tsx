import { notFound } from 'next/navigation'
import Link from 'next/link'
import { Award, Package, Gem } from 'lucide-react'
import { ProductPageClient } from './ProductPageClient'
import { ProductImageGallery } from './ProductImageGallery'
import { ProductCard } from '@/components/product'
import { ItemAvailability } from '@/lib/domain-states'
import { COPY } from '@/lib/contract-copy'
import { MOCK_CATALOG, getBreakdown, MOCK_THUMBNAILS } from '@/mocks/catalog-data'

const TRUST = [
  { icon: Award,   text: COPY.product.trustCert     },
  { icon: Gem,     text: COPY.product.trustUnique    },
  { icon: Package, text: COPY.product.trustShipping  },
]

export default async function ProductPage({
  params,
}: {
  params: Promise<{ slug: string }>
}) {
  const { slug } = await params

  const product = MOCK_CATALOG.find(p => p.slug === slug)
  if (!product || product.availability === ItemAvailability.SOLD) notFound()

  const breakdown  = getBreakdown(product.id, product)
  const thumbnails = MOCK_THUMBNAILS[product.id] ?? []

  const SPECS = [
    { label: COPY.product.specKarat,    value: COPY.product.specValue.karat(product.karat)   },
    { label: COPY.product.specWeight,   value: COPY.product.specValue.weight(product.weight) },
    { label: COPY.product.specMaterial, value: COPY.product.specValue.material               },
    { label: COPY.product.specStone,    value: COPY.product.specValue.stone                  },
  ]

  // Similar pieces: same karat, different item, available/reserved only
  const similar = MOCK_CATALOG
    .filter(p => p.id !== product.id && p.karat === product.karat)
    .slice(0, 3)

  return (
    <main className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 pb-16">
      {/* Two-column product layout */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 lg:gap-12">

        {/* Left: image gallery */}
        <ProductImageGallery
          mainImg={product.img}
          name={product.name}
          thumbnails={thumbnails}
        />

        {/* Right column */}
        <div className="flex flex-col gap-5">
          {/* Piece number + unique badge */}
          <p className="text-muted text-xs flex items-center gap-2" dir="ltr">
            <span className="tabular-nums">{COPY.product.pieceNumberLabel}{'  '}{product.id}</span>
            <span className="text-gold/60">·</span>
            <span dir="rtl">{COPY.product.trustUnique}</span>
          </p>

          {/* Name */}
          <h1 className="text-2xl font-semibold text-charcoal tracking-[-0.02em] -mt-2">
            {product.name}
          </h1>

          {/* Specs table */}
          <table className="w-full text-sm border-collapse" aria-label="مواصفات القطعة">
            <tbody>
              {SPECS.map(({ label, value }) => (
                <tr key={label} className="border-b border-gold/10 last:border-0">
                  <td className="py-2 text-muted font-medium w-28">{label}</td>
                  <td className="py-2 text-charcoal tabular-nums">{value}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* Interactive pricing card */}
          <ProductPageClient
            itemId={product.id}
            itemName={product.name}
            price={product.price}
            breakdownItems={breakdown}
          />

          {/* Trust row */}
          <div className="flex flex-wrap gap-4 border-t border-gold/10 pt-4">
            {TRUST.map(({ icon: Icon, text }) => (
              <div key={text} className="flex items-center gap-1.5 text-muted text-xs">
                <Icon size={13} className="text-gold shrink-0" aria-hidden="true" />
                {text}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Similar pieces strip */}
      {similar.length > 0 && (
        <section className="mt-14 pt-8 border-t border-gold/15">
          <div className="flex items-baseline justify-between mb-6">
            <h2 className="text-lg font-semibold text-charcoal tracking-[-0.02em]">
              {COPY.product.similarTitle}
            </h2>
            <Link
              href="/jewellery/rings"
              className="text-xs text-muted hover:text-charcoal transition-colors"
            >
              {COPY.home.viewAllCta}
            </Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 sm:gap-5">
            {similar.map(p => <ProductCard key={p.id} product={p} />)}
          </div>
        </section>
      )}
    </main>
  )
}

export function generateStaticParams() {
  return MOCK_CATALOG.map(p => ({ slug: p.slug }))
}
