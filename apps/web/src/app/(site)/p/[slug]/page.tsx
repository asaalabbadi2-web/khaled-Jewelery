import { notFound } from 'next/navigation'
import Link from 'next/link'
import { Award, Package, Gem } from 'lucide-react'
import { ProductPageClient } from './ProductPageClient'
import { ProductImageGallery } from './ProductImageGallery'
import { ProductCard } from '@/components/product'
import { ItemAvailability } from '@/lib/domain-states'
import { COPY } from '@/lib/contract-copy'
import {
  fetchProductDetail,
  fetchProducts,
  toCatalogCardItem,
  toBreakdownRows,
} from '@/lib/api/server'

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

  const product = await fetchProductDetail(slug)
  if (!product || product.stock === 0) notFound()

  const breakdown = toBreakdownRows(product)

  const SPECS = [
    { label: COPY.product.specKarat,    value: COPY.product.specValue.karat(parseInt(product.karat ?? '21', 10) as 18 | 21 | 22 | 24) },
    { label: COPY.product.specWeight,   value: COPY.product.specValue.weight(product.weight ?? 0) },
    { label: COPY.product.specMaterial, value: COPY.product.specValue.material },
    { label: COPY.product.specStone,    value: COPY.product.specValue.stone    },
  ]

  // Similar pieces: same karat, different slug, in-stock
  const allKarat   = await fetchProducts({ karat: product.karat ?? undefined, in_stock: true, page_size: 10 })
  const similar    = allKarat
    .filter(p => p.slug !== slug)
    .slice(0, 3)
    .map(toCatalogCardItem)

  return (
    <main className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 pb-16">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 lg:gap-12">

        <ProductImageGallery
          mainImg={undefined}
          name={product.name}
          thumbnails={[]}
        />

        <div className="flex flex-col gap-5">
          <p className="text-muted text-xs flex items-center gap-2" dir="ltr">
            <span className="tabular-nums">{COPY.product.pieceNumberLabel}{'  '}{product.item_code}</span>
            <span className="text-gold/60">·</span>
            <span dir="rtl">{COPY.product.trustUnique}</span>
          </p>

          <h1 className="text-2xl font-semibold text-charcoal tracking-[-0.02em] -mt-2">
            {product.name}
          </h1>

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

          <ProductPageClient
            itemId={product.slug}
            itemName={product.name}
            price={product.price ?? 0}
            breakdownItems={breakdown}
          />

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

// Dynamic rendering — product availability changes in real time
export const dynamic = 'force-dynamic'
