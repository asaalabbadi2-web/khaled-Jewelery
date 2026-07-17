import { ItemAvailability } from '@/lib/domain-states'
import { pr } from '@/lib/format'
import { ProductImage } from './ProductImage'
import { ProductSpecs } from './ProductSpecs'
import { ProductPricePreview } from './ProductPricePreview'
import { ProductAvailabilityBadge } from './ProductAvailabilityBadge'

export interface ProductCardItem {
  id: string
  name: string
  karat: 18 | 21 | 22 | 24
  weight: number
  price: number
  availability: ItemAvailability
  img?: string
}

export interface ProductCardProps {
  product: ProductCardItem
  onView(): void
  /** Shows a stale-price timestamp next to the price */
  stalePriceLabel?: string
}

export function ProductCard({ product, onView, stalePriceLabel }: ProductCardProps) {
  const reserved = product.availability === ItemAvailability.RESERVED
  const sold     = product.availability === ItemAvailability.SOLD

  return (
    <button
      type="button"
      onClick={onView}
      className={`group cursor-pointer text-right w-full transition-opacity duration-200 ${reserved || sold ? 'opacity-[0.70]' : ''}`}
      aria-label={`${product.name}، ${product.karat}K، ${product.weight}غ، ${pr(product.price)} ريال`}
    >
      <ProductImage
        src={product.img}
        name={product.name}
        reserved={reserved}
      />
      <p className="text-charcoal text-sm font-medium leading-snug">{product.name}</p>
      <ProductSpecs karat={product.karat} weight={product.weight} />
      <ProductPricePreview price={product.price} stalePriceLabel={stalePriceLabel} />
      <ProductAvailabilityBadge availability={product.availability} />
    </button>
  )
}
