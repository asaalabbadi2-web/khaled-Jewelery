import type { Meta, StoryObj } from '@storybook/react'
import { GoldLiveBar } from './GoldLiveBar'

// STATE_STORY_REGISTRY: GoldLiveBar
// FRESH  → covered (age=30,  halted=false)
// STALE  → covered (age=180, halted=false)
// HALTED → covered (age=30,  halted=true)

const MOCK_RATES = { karat24: 330.15, karat21: 289.38 }

const meta: Meta<typeof GoldLiveBar> = {
  title: 'Components/GoldLiveBar',
  component: GoldLiveBar,
  parameters: { layout: 'fullscreen' },
  args: { rates: MOCK_RATES },
}
export default meta

type Story = StoryObj<typeof GoldLiveBar>

export const Fresh: Story = {
  args: { age: 30, halted: false },
}

export const Stale: Story = {
  args: { age: 180, halted: false },
}

export const Halted: Story = {
  args: { age: 30, halted: true },
}
