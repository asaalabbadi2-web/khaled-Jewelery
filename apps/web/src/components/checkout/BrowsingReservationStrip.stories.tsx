import type { Meta, StoryObj } from '@storybook/react'
import { BrowsingReservationStrip } from './BrowsingReservationStrip'

// STATE_STORY_REGISTRY: BrowsingReservationStrip
// ACTIVE → covered (reservation active, normal countdown, gold «إتمام الدفع» link)
// URGENT → covered (≤60 s, amber countdown)

const meta: Meta<typeof BrowsingReservationStrip> = {
  title: 'Components/BrowsingReservationStrip',
  component: BrowsingReservationStrip,
  parameters: { layout: 'fullscreen' },
  args: { checkoutHref: '/checkout?rid=RSV-001' },
  decorators: [
    (Story) => (
      <div className="bg-surface min-h-24">
        <Story />
      </div>
    ),
  ],
}
export default meta

type Story = StoryObj<typeof BrowsingReservationStrip>

export const Active: Story = {
  args: { count: 1, ms: 7 * 60_000 + 30_000 },
}

export const Urgent: Story = {
  args: { count: 1, ms: 45_000 },
}
