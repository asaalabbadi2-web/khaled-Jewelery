import type { Meta, StoryObj } from '@storybook/react'
import { ReservationStrip } from './ReservationStrip'
import { RESERVATION_MS } from '@/lib/server-clock'

// STATE_STORY_REGISTRY: ReservationStrip
// NORMAL → covered (plenty of time, gold bar)
// URGENT → covered (≤60s, amber text + bar)
// FROZEN → covered (offline — frozen badge, dimmed)

const meta: Meta<typeof ReservationStrip> = {
  title: 'Components/ReservationStrip',
  component: ReservationStrip,
  parameters: { layout: 'fullscreen' },
  args: { reservationMs: RESERVATION_MS },
  decorators: [
    (Story) => (
      <div className="pt-12">
        <Story />
      </div>
    ),
  ],
}
export default meta

type Story = StoryObj<typeof ReservationStrip>

export const Normal: Story = {
  args: { ms: 7 * 60_000 + 30_000 },
}

export const Urgent: Story = {
  args: { ms: 45_000 },
}

export const Frozen: Story = {
  args: { ms: 5 * 60_000, frozen: true },
}
