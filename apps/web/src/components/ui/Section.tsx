import { type ReactNode } from 'react'

/**
 * Full-bleed section with the standard max-width centred container.
 * Used for every page section that needs the 6xl gutter + responsive padding.
 */
interface SectionProps {
  children: ReactNode
  as?: 'section' | 'div' | 'main' | 'article' | 'aside'
  ariaLabelledBy?: string
  ariaLabel?: string
  className?: string
  innerClassName?: string
}

export function Section({
  children,
  as: Tag = 'section',
  ariaLabelledBy,
  ariaLabel,
  className = '',
  innerClassName = '',
}: SectionProps) {
  return (
    <Tag
      aria-labelledby={ariaLabelledBy}
      aria-label={ariaLabel}
      className={className}
    >
      <div
        className={`max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 ${innerClassName}`}
      >
        {children}
      </div>
    </Tag>
  )
}
