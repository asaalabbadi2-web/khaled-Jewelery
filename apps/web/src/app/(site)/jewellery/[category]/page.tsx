import { ProductCard } from '@/components/product'
import { ItemAvailability } from '@/lib/domain-states'

// Mock catalog data — MSW handler replaces this in dev; real API in prod.
const CATALOG = [
  { id: 'R-21-0342', name: 'خاتم سوليتير',  karat: 21 as const, weight: 8.45,  price: 1_215, availability: ItemAvailability.AVAILABLE, img: 'https://images.unsplash.com/photo-1605100804763-247f67b3557e?w=600&h=600&fit=crop&auto=format' },
  { id: 'R-21-0418', name: 'خاتم تريلوجي',  karat: 21 as const, weight: 9.30,  price: 2_340, availability: ItemAvailability.RESERVED,  img: 'https://images.unsplash.com/photo-1589128777073-263566ae5e4d?w=600&h=600&fit=crop&auto=format' },
  { id: 'R-18-0314', name: 'خاتم هالو',      karat: 18 as const, weight: 5.60,  price: 1_480, availability: ItemAvailability.AVAILABLE, img: 'https://images.unsplash.com/photo-1598560917807-1bae44bd2be8?w=600&h=600&fit=crop&auto=format' },
  { id: 'R-21-0385', name: 'خاتم بافلي',     karat: 21 as const, weight: 7.20,  price: 1_651, availability: ItemAvailability.AVAILABLE, img: 'https://images.unsplash.com/photo-1611955167811-4711904bb9f8?w=600&h=600&fit=crop&auto=format' },
  { id: 'R-21-0466', name: 'خاتم فينيتاج',   karat: 21 as const, weight: 11.80, price: 3_050, availability: ItemAvailability.AVAILABLE, img: 'https://images.unsplash.com/photo-1602173574767-37ac01994b2a?w=600&h=600&fit=crop&auto=format' },
  { id: 'R-21-0399', name: 'خاتم كلاسيك',    karat: 21 as const, weight: 7.80,  price: 1_790, availability: ItemAvailability.AVAILABLE, img: 'https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=600&h=600&fit=crop&auto=format' },
  { id: 'B-21-0101', name: 'سوار ترولوجي',   karat: 21 as const, weight: 6.10,  price: 1_400, availability: ItemAvailability.AVAILABLE, img: 'https://images.unsplash.com/photo-1573408301185-9519f94816b5?w=600&h=600&fit=crop&auto=format' },
  { id: 'N-21-0202', name: 'عقد سوليتير',    karat: 21 as const, weight: 4.30,  price: 990,   availability: ItemAvailability.AVAILABLE, img: 'https://images.unsplash.com/photo-1515562141207-7a88fb7ce338?w=600&h=600&fit=crop&auto=format' },
]

export default function CatalogPage() {
  return (
    <main className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 pb-16">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4 sm:gap-5">
        {CATALOG.map((product) => (
          <ProductCard
            key={product.id}
            product={product}
            onView={() => {}}
          />
        ))}
      </div>
    </main>
  )
}

export function generateStaticParams() {
  return [{ category: 'rings' }, { category: 'bracelets' }, { category: 'necklaces' }, { category: 'sets' }]
}
