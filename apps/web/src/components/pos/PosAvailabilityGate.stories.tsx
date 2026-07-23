import type { Meta, StoryObj } from '@storybook/react'
import { PosAvailabilityGate } from './PosAvailabilityGate'

// STATE_STORY_REGISTRY: PosAvailabilityGate (Gate B Frontend)
// IDLE        → covered: pre-check prompt, "تحقق" button only
// CHECKING    → covered: spinner / pulse text, no action buttons
// AVAILABLE   → covered: green badge, "تأكيد البيع" + retry buttons
// RESERVED    → covered: red badge, blocked message, retry only (no confirm)
// TIMEOUT     → covered: amber badge, fail-open warning, proceed + retry
// UNREACHABLE → covered: amber badge, fail-open warning, proceed + retry

const noop = () => {}

const meta: Meta<typeof PosAvailabilityGate> = {
  title: 'Components/POS/PosAvailabilityGate',
  component: PosAvailabilityGate,
  parameters: { layout: 'padded' },
  decorators: [
    (Story) => (
      <div className="max-w-sm">
        <Story />
      </div>
    ),
  ],
  args: {
    onCheck:   noop,
    onConfirm: noop,
  },
}
export default meta

type Story = StoryObj<typeof PosAvailabilityGate>

// IDLE — operator has not triggered a check yet.
export const Idle: Story = {
  args: { state: { kind: 'IDLE' } },
}

// CHECKING — fetch in flight; no action buttons rendered.
export const Checking: Story = {
  args: { state: { kind: 'CHECKING' } },
}

// AVAILABLE — Commerce confirmed no active reservation; sale may proceed.
export const Available: Story = {
  args: { state: { kind: 'AVAILABLE' } },
}

// RESERVED — active online reservation; sale is blocked until expiry.
export const Reserved: Story = {
  args: {
    state: {
      kind:          'RESERVED',
      reservedUntil: '2026-07-19T15:00:00+03:00',
      reservationId: 'RES-4a9f1',
    },
  },
}

// TIMEOUT — Commerce API did not respond within 5 s; fail-open (proceed with warning).
export const Timeout: Story = {
  args: { state: { kind: 'TIMEOUT' } },
}

// UNREACHABLE — Commerce API connection failed; fail-open (proceed with warning).
export const Unreachable: Story = {
  args: { state: { kind: 'UNREACHABLE' } },
}
