/**
 * FC-1 — Domain State Visibility gate.
 * Every (component, state) pair in STATE_STORY_REGISTRY must have a
 * corresponding named export in the story file.
 *
 * Red→green demo: HALTED is intentionally missing from GoldLiveBar.stories.tsx.
 * This test fails until you add the Halted story.
 */
import { describe, it, expect } from 'vitest'

// Registry: [component, state, storyExportName]
const STATE_STORY_REGISTRY: Array<[string, string, string]> = [
  ['GoldLiveBar', 'FRESH',  'Fresh'],
  ['GoldLiveBar', 'STALE',  'Stale'],
  ['GoldLiveBar', 'HALTED', 'Halted'],
]

describe('State coverage', () => {
  it('every registered state has a story', async () => {
    const goldLiveBarStories = await import(
      '../components/GoldLiveBar.stories'
    )

    const missing: string[] = []

    for (const [component, state, exportName] of STATE_STORY_REGISTRY) {
      const storyModule =
        component === 'GoldLiveBar' ? goldLiveBarStories : null

      if (!storyModule || !(exportName in storyModule)) {
        missing.push(`${component}/${state} (export: ${exportName})`)
      }
    }

    expect(missing, `Missing stories:\n${missing.join('\n')}`).toHaveLength(0)
  })
})
