import type { Meta, StoryObj } from '@storybook/react'
import { OrderTimeline } from './OrderTimeline'

// STATE_STORY_REGISTRY: OrderTimeline
// ACTIVE            → covered (step 2 active — preparing)
// SHIPMENT_CREATED  → covered (step 3 active — shipment ready)
// SHIPPED           → covered (step 4 active — out for delivery)
// DELIVERED         → covered (all steps done)
// CANCELLED         → covered (first step done, remaining greyed out / not active)

const BASE_STEPS = [
  { label: 'تم الدفع',                              done: false, active: false },
  { label: 'جارٍ تجهيز القطعة',                     done: false, active: false },
  { label: 'جُهّزت الشحنة (مؤمَّنة بالكامل)',       done: false, active: false },
  { label: 'خرجت للتوصيل',                           done: false, active: false },
  { label: 'تم التسليم',                             done: false, active: false },
]

const STEPS_ACTIVE = BASE_STEPS.map((s, i) => ({
  ...s,
  done:   i < 1,
  active: i === 1,
}))

const STEPS_SHIPMENT_CREATED = BASE_STEPS.map((s, i) => ({
  ...s,
  done:   i < 2,
  active: i === 2,
}))

const STEPS_SHIPPED = BASE_STEPS.map((s, i) => ({
  ...s,
  done:   i < 3,
  active: i === 3,
}))

const STEPS_DELIVERED = BASE_STEPS.map(s => ({ ...s, done: true, active: false }))

const STEPS_CANCELLED = BASE_STEPS.map((s, i) => ({
  ...s,
  done:   i === 0,
  active: false,
}))

const meta: Meta<typeof OrderTimeline> = {
  title: 'Components/OrderTimeline',
  component: OrderTimeline,
  parameters: { layout: 'padded' },
  decorators: [
    (Story) => (
      <div className="max-w-xs bg-surface p-5 rounded-sm">
        <Story />
      </div>
    ),
  ],
}
export default meta

type Story = StoryObj<typeof OrderTimeline>

export const Active: Story = {
  args: { steps: STEPS_ACTIVE },
}

export const ShipmentCreated: Story = {
  args: { steps: STEPS_SHIPMENT_CREATED },
}

export const Shipped: Story = {
  args: { steps: STEPS_SHIPPED },
}

export const Delivered: Story = {
  args: { steps: STEPS_DELIVERED },
}

export const Cancelled: Story = {
  args: { steps: STEPS_CANCELLED },
}
