import type { Meta, StoryObj } from '@storybook/react'
import { ProductCard } from './ProductCard'
import { SkeletonCard } from './SkeletonCard'
import { ItemAvailability } from '@/lib/domain-states'

// STATE_STORY_REGISTRY: ProductCard
// AVAILABLE       → covered (live product, available)
// RESERVED        → covered (reserved-by-other, opacity-70, amber badge)
// IMAGE_FALLBACK  → covered (no img → diamond ◇ fallback)

const BASE_PRODUCT = {
  id: 'p-001',
  name: 'خاتم زفاف كلاسيكي',
  karat: 21 as const,
  weight: 4.85,
  price: 1404.00,
  img: 'https://images.unsplash.com/photo-1605100804763-247f67b3557e?w=400',
}

const meta: Meta<typeof ProductCard> = {
  title: 'Components/ProductCard',
  component: ProductCard,
  parameters: { layout: 'padded' },
  decorators: [
    (Story) => (
      <div className="max-w-xs">
        <Story />
      </div>
    ),
  ],
  args: {
    onView: () => {},
  },
}
export default meta

type Story = StoryObj<typeof ProductCard>

export const Available: Story = {
  args: {
    product: { ...BASE_PRODUCT, availability: ItemAvailability.AVAILABLE },
  },
}

export const Reserved: Story = {
  args: {
    product: { ...BASE_PRODUCT, availability: ItemAvailability.RESERVED },
  },
}

export const ImageFallback: Story = {
  args: {
    product: { ...BASE_PRODUCT, availability: ItemAvailability.AVAILABLE, img: undefined },
  },
}

export const Skeleton: Story = {
  render: () => (
    <div className="max-w-xs">
      <SkeletonCard />
    </div>
  ),
}
