import { PricingCard } from '@/components/pricing'
import { Skeleton } from '@/components/ui'

// Mock product data — wired to MSW in dev; real Commerce API in prod.
const MOCK_PRODUCT = {
  name: 'خاتم سوليتير',
  karat: 21,
  weight: 8.45,
  price: 1_214.69,
  img: 'https://images.unsplash.com/photo-1605100804763-247f67b3557e?w=800&h=1000&fit=crop&auto=format',
}

const BREAKDOWN = [
  { label: 'مكوّن الذهب (8.450غ × 289.40)', value: '2,445.43' },
  { label: 'المصنعية',                        value: '350.00' },
  { label: 'الأحجار',                         value: '220.00' },
  { label: 'الضريبة (15%)',                   value: '452.31' },
]

export default function ProductPage() {
  return (
    <main className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 pb-16">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 lg:gap-12">
        {/* Product image */}
        <div
          className="relative overflow-hidden rounded-sm bg-image-bg"
          style={{ aspectRatio: '4/5' }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={MOCK_PRODUCT.img}
            alt={MOCK_PRODUCT.name}
            className="w-full h-full object-cover mix-blend-multiply"
          />
        </div>

        {/* Right column: name + specs + pricing card */}
        <div className="flex flex-col gap-4">
          <h1 className="text-2xl font-semibold text-charcoal tracking-[-0.02em]">
            {MOCK_PRODUCT.name}
          </h1>
          <p className="text-muted text-sm">
            <span dir="ltr" className="tabular-nums">{MOCK_PRODUCT.karat}K</span>
            {' · '}
            <span dir="ltr" className="tabular-nums">{MOCK_PRODUCT.weight.toFixed(2)}</span>
            {'غ'}
          </p>

          <PricingCard
            state="DEFAULT"
            price={MOCK_PRODUCT.price}
            ageSeconds={18}
            breakdownItems={BREAKDOWN}
          />
        </div>
      </div>
    </main>
  )
}

export function generateStaticParams() {
  return [{ slug: 'R-21-0342' }]
}
