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

const WHY_US = [
  { icon: TrendingUp, text: 'سعر مباشر من سوق الذهب' },
  { icon: Gem,        text: 'قطعة واحدة لا تتكرر' },
  { icon: Award,      text: 'شهادة أصالة مع كل قطعة' },
  { icon: Package,    text: 'شحن مؤمَّن حتى باب المنزل' },
]

export default function HomePage() {
  return (
    <main>
      {/* Hero */}
      <section className="px-4 sm:px-6 lg:px-8 pb-16 text-center">
        <h1 className="text-3xl sm:text-[2.25rem] font-semibold tracking-[-0.02em] text-charcoal leading-snug mb-3">
          {COPY.home.heroTitle}
        </h1>
        <p className="text-muted text-sm mb-2">{COPY.home.heroSub}</p>
        <p className="text-muted text-sm mb-8">{COPY.home.browseCta}</p>
      </section>

      {/* Featured products */}
      <section
        className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 pb-16"
        aria-label="قطع مميزة"
      >
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4 sm:gap-5">
          {FEATURED.map((product) => (
            <ProductCard
              key={product.id}
              product={product}
              onView={() => {}}
            />
          ))}
        </div>
      </section>

      {/* Why us */}
      <section className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 pb-16 border-t border-gold/15 pt-10">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-5">
          {WHY_US.map(({ icon: Icon, text }) => (
            <div key={text} className="flex items-center gap-2 text-muted text-xs">
              <span className="text-gold"><Icon size={16} /></span>
              {text}
            </div>
          ))}
        </div>
      </section>
    </main>
  )
}
