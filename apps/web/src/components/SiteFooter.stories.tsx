import type { Meta, StoryObj } from '@storybook/react'
import { SiteFooter } from './SiteFooter'

// STATE_STORY_REGISTRY: SiteFooter
// DEFAULT → covered (all 7 links, priceNote)

const meta: Meta<typeof SiteFooter> = {
  title: 'Components/SiteFooter',
  component: SiteFooter,
  parameters: { layout: 'fullscreen' },
  args: {
    onSelect:  (name) => console.log('selected:', name),
    onCatalog: () => {},
    onTrack:   () => {},
  },
}
export default meta

type Story = StoryObj<typeof SiteFooter>

export const Default: Story = {}
