import Link from 'next/link'
import { Award, Package, Gem } from 'lucide-react'
import { ProductPageClient } from './ProductPageClient'
import { ProductImageGallery } from './ProductImageGallery'
import { ProductCard } from '@/components/product'
import { ItemAvailability } from '@/lib/domain-states'
import { COPY } from '@/lib/contract-copy'

const MOCK_PRODUCT = {
  id:      'R-21-0342',
  name:    'خاتم سوليتير',
  karat:   21,
  weight:  8.45,
  price:   1_214.69,
  stone:   COPY.product.specValue.stone,
  material:COPY.product.specValue.material,
  img:     'https://images.unsplash.com/photo-1605100804763-247f67b3557e?w=800&h=1000&fit=crop&auto=format',
  thumbnails: [
    'https://images.unsplash.com/photo-1589128777073-263566ae5e4d?w=600&h=750&fit=crop&auto=format',
    'https://images.unsplash.com/photo-1598560917807-1bae44bd2be8?w=600&h=750&fit=crop&auto=format',
  ],
}

const BREAKDOWN = [
  { label: 'مكوّن الذهب (8.450غ × 289.40)', value: '2,445.43' },
  { label: 'المصنعية',                        value: '350.00'   },
  { label: 'الأحجار',                         value: '220.00'   },
  { label: 'الضريبة (15%)',                   value: '452.31'   },
]

const SIMILAR = [
  { id: 'R-21-0418', name: 'خاتم تريلوجي',  karat: 21 as const, weight: 9.30,  price: 2_340, availability: ItemAvailability.RESERVED,  img: 'https://images.unsplash.com/photo-1589128777073-263566ae5e4d?w=600&h=600&fit=crop&auto=format' },
  { id: 'R-21-0385', name: 'خاتم بافلي',     karat: 21 as const, weight: 7.20,  price: 1_651, availability: ItemAvailability.AVAILABLE, img: 'https://images.unsplash.com/photo-1611955167811-4711904bb9f8?w=600&h=600&fit=crop&auto=format' },
  { id: 'R-21-0399', name: 'خاتم كلاسيك',    karat: 21 as const, weight: 7.80,  price: 1_790, availability: ItemAvailability.AVAILABLE, img: 'https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=600&h=600&fit=crop&auto=format' },
]

const SPECS = [
  { label: COPY.product.specKarat,    value: COPY.product.specValue.karat(MOCK_PRODUCT.karat) },
  { label: COPY.product.specWeight,   value: COPY.product.specValue.weight(MOCK_PRODUCT.weight) },
  { label: COPY.product.specMaterial, value: MOCK_PRODUCT.material },
  { label: COPY.product.specStone,    value: MOCK_PRODUCT.stone },
]

const TRUST = [
  { icon: Award,   text: COPY.product.trustCert     },
  { icon: Gem,     text: COPY.product.trustUnique    },
  { icon: Package, text: COPY.product.trustShipping  },
]

export default function ProductPage() {
  return (
    <main className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 pb-16">
      {/* Two-column product layout */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 lg:gap-12">

        {/* Left: image gallery */}
        <ProductImageGallery
          mainImg={MOCK_PRODUCT.img}
          name={MOCK_PRODUCT.name}
          thumbnails={MOCK_PRODUCT.thumbnails}
        />

        {/* Right column */}
        <div className="flex flex-col gap-5">
          {/* Piece number row */}
          <p className="text-muted text-xs tabular-nums" dir="ltr">
            {COPY.product.pieceNumberLabel}{'  '}{MOCK_PRODUCT.id}
          </p>

          {/* Name */}
          <h1 className="text-2xl font-semibold text-charcoal tracking-[-0.02em] -mt-2">
            {MOCK_PRODUCT.name}
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
            itemId={MOCK_PRODUCT.id}
            price={MOCK_PRODUCT.price}
            breakdownItems={BREAKDOWN}
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
          {SIMILAR.map(p => <ProductCard key={p.id} product={p} />)}
        </div>
      </section>
    </main>
  )
}

export function generateStaticParams() {
  return [{ slug: 'R-21-0342' }]
}
