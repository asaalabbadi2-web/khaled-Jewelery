import type { Meta, StoryObj } from '@storybook/react'
import { GoldLiveBar } from './GoldLiveBar'

// STATE_STORY_REGISTRY: GoldLiveBar
// FRESH  → covered (ageSeconds=30)
// STALE  → covered (ageSeconds=180)
// HALTED → covered (ageSeconds=null)   ← added in red→green demo

const meta: Meta<typeof GoldLiveBar> = {
  title: 'Components/GoldLiveBar',
  component: GoldLiveBar,
  parameters: {
    layout: 'fullscreen',
  },
}
export default meta

type Story = StoryObj<typeof GoldLiveBar>

export const Fresh: Story = {
  args: { ageSeconds: 30 },
}

export const Stale: Story = {
  args: { ageSeconds: 180 },
}

// Red→green cycle: this story was added after state-coverage.test.ts failed
// with "Missing stories: GoldLiveBar/HALTED". Adding it → test passes.
export const Halted: Story = {
  args: { ageSeconds: null },
}
