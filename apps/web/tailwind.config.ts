import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Brand palette — single source of truth (FC-5)
        // HEX→TOKEN map: no raw hex may survive migration
        ivory:        '#F7F4EE',
        surface:      '#FBFAF7',
        gold:         '#C9A96A',
        bronze:       '#8C6F4E',
        'bronze-hover': '#7A5F40',
        charcoal:     '#2B2B28',
        success:      '#5C7A5E',
        warning:      '#B08A3E',
        error:        '#9B4A3C',
        muted:        '#7A7570',
        'muted-2':    '#9B9892',
        skeleton:     '#E8E3D8',
        'image-bg':   '#EDE8DF',
      },
      fontFamily: {
        // IBM Plex Sans Arabic via next/font (injected in layout)
        sans: ['var(--font-ibm-plex-arabic)', 'system-ui', 'sans-serif'],
      },
      fontVariantNumeric: {
        tabular: 'tabular-nums',
      },
    },
  },
  plugins: [],
}

export default config
