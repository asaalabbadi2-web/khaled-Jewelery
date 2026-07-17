import type { Meta, StoryObj } from '@storybook/react'
import { SiteHeader } from './SiteHeader'

// STATE_STORY_REGISTRY: SiteHeader
// DEFAULT       → covered (no active page, no banner)
// CATALOG_ACTIVE → covered (active=catalog)
// TRACK_ACTIVE   → covered (active=track)
// WITH_BANNER    → covered (hasBanner=true)

const meta: Meta<typeof SiteHeader> = {
  title: 'Components/SiteHeader',
  component: SiteHeader,
  parameters: { layout: 'fullscreen' },
  args: {
    onHome:    () => {},
    onCatalog: () => {},
    onAbout:   () => {},
    onTrack:   () => {},
  },
}
export default meta

type Story = StoryObj<typeof SiteHeader>

export const Default: Story = {}

export const CatalogActive: Story = {
  args: { active: 'catalog' },
}

export const TrackActive: Story = {
  args: { active: 'track' },
}

export const WithBanner: Story = {
  args: { hasBanner: true },
  decorators: [
    (Story) => (
      <div className="bg-charcoal h-10 w-full fixed top-0" aria-hidden="true">
        <Story />
      </div>
    ),
  ],
}
