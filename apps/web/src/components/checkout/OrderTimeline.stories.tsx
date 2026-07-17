import type { Meta, StoryObj } from '@storybook/react'
import { OrderTimeline } from './OrderTimeline'

// STATE_STORY_REGISTRY: OrderTimeline
// ACTIVE    → covered (2 steps done, current step active, future steps pending)
// DELIVERED → covered (all steps done)
// REFUNDED  → separate OrderTimeline story with refund-specific steps

const STEPS_ACTIVE = [
  { label: 'تم الدفع',                              done: true,  active: false },
  { label: 'جارٍ تجهيز القطعة',                     done: true,  active: false },
  { label: 'جُهّزت الشحنة (مؤمَّنة بالكامل)',       done: false, active: true  },
  { label: 'خرجت للتوصيل',                           done: false, active: false },
  { label: 'تم التسليم',                             done: false, active: false },
]

const STEPS_DELIVERED = STEPS_ACTIVE.map(s => ({ ...s, done: true, active: false }))

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

export const Delivered: Story = {
  args: { steps: STEPS_DELIVERED },
}
