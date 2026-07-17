import type { Meta, StoryObj } from '@storybook/react'
import { PricingCard } from './PricingCard'

// STATE_STORY_REGISTRY: PricingCard
// DEFAULT           → covered (price visible, reserve CTA, gold breakdown)
// RESERVED          → covered (lock badge, countdown, checkout CTA)
// EXPIRED           → covered (old/new price comparison, reserve-new CTA)
// STALE             → covered (dimmed price, amber pulse, disabled CTA)
// HALTED            → covered (halted banner, disabled CTA)
// RESERVED_BY_OTHER → covered (reserved by other message, browse CTA)
// RACE_CONFLICT     → covered (race info box, browse CTA)
// SOLD              → covered (sold message, browse CTA)
// PAYMENT_VERIFYING → covered (spinner, verifying text)
// LATE_PAYMENT      → covered (late payment notice)
// REFUNDED          → covered (CheckCircle, refunded note, browse CTA)
// OFFLINE           → covered (frozen countdown, wifi-off banner, disabled CTA)
// SKELETON          → covered (shimmer placeholders)

const PRICE    = 1_214.69
const PRICE_NEW = 1_219.20
const BREAKDOWN = [
  { label: 'مكوّن الذهب (8.450غ × 289.40)', value: '2,445.43' },
  { label: 'المصنعية',                        value: '350.00' },
  { label: 'الأحجار',                         value: '220.00' },
  { label: 'الضريبة (15%)',                   value: '452.31' },
]
const noop = () => {}

const meta: Meta<typeof PricingCard> = {
  title: 'Components/PricingCard',
  component: PricingCard,
  parameters: { layout: 'padded' },
  decorators: [
    (Story) => (
      <div className="max-w-sm mx-auto">
        <Story />
      </div>
    ),
  ],
  args: {
    price:    PRICE,
    priceNew: PRICE_NEW,
    ageSeconds: 42,
    breakdownItems: BREAKDOWN,
    onReserve:    noop,
    onCancel:     noop,
    onReserveNew: noop,
    onCheckout:   noop,
    onBrowse:     noop,
  },
}
export default meta

type Story = StoryObj<typeof PricingCard>

export const Default: Story = {
  args: { state: 'DEFAULT' },
}

export const Reserved: Story = {
  args: { state: 'RESERVED', ms: 7 * 60_000 + 30_000 },
}

export const Expired: Story = {
  args: { state: 'EXPIRED' },
}

export const Stale: Story = {
  args: { state: 'STALE' },
}

export const Halted: Story = {
  args: { state: 'HALTED' },
}

export const ReservedByOther: Story = {
  args: { state: 'RESERVED_BY_OTHER' },
}

export const RaceConflict: Story = {
  args: { state: 'RACE_CONFLICT' },
}

export const Sold: Story = {
  args: { state: 'SOLD' },
}

export const PaymentVerifying: Story = {
  args: { state: 'PAYMENT_VERIFYING' },
}

export const LatePayment: Story = {
  args: { state: 'LATE_PAYMENT' },
}

export const Refunded: Story = {
  args: { state: 'REFUNDED' },
}

export const Offline: Story = {
  args: { state: 'OFFLINE', ms: 5 * 60_000 },
}

export const Skeleton: Story = {
  args: { state: 'SKELETON' },
}
