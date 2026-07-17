import type { Preview, Decorator } from '@storybook/react'
import { IBM_Plex_Sans_Arabic } from 'next/font/google'
import '../src/app/globals.css'

const ibmPlex = IBM_Plex_Sans_Arabic({
  subsets: ['arabic', 'latin'],
  weight: ['300', '400', '500', '600'],
  variable: '--font-ibm-plex-arabic',
})

const RtlDecorator: Decorator = (Story) => (
  <div
    dir="rtl"
    lang="ar"
    className={`${ibmPlex.variable} font-sans bg-ivory min-h-screen p-4`}
  >
    <Story />
  </div>
)

const preview: Preview = {
  decorators: [RtlDecorator],
  parameters: {
    layout: 'fullscreen',
    backgrounds: {
      default: 'ivory',
      values: [
        { name: 'ivory', value: '#F7F4EE' },
        { name: 'white', value: '#FFFFFF' },
      ],
    },
  },
}

export default preview
