import type { Meta, StoryObj } from '@storybook/react'
import { OtpInput } from './OtpInput'

// STATE_STORY_REGISTRY: OtpInput
// DEFAULT → covered (empty 6-digit inputs, awaiting user entry)

const meta: Meta<typeof OtpInput> = {
  title: 'Components/OtpInput',
  component: OtpInput,
  parameters: { layout: 'centered' },
  args: {
    onComplete: (code: string) => console.log('OTP complete:', code),
  },
}
export default meta

type Story = StoryObj<typeof OtpInput>

export const Default: Story = {}
