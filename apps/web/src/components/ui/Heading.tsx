import { type ReactNode } from 'react'

type HeadingLevel = 'h1' | 'h2' | 'h3' | 'h4'
type HeadingSize  = 'xl' | 'lg' | 'base' | 'sm'

const sizeClasses: Record<HeadingSize, string> = {
  xl:   'text-3xl md:text-[2.25rem] font-semibold leading-snug tracking-[-0.02em]',
  lg:   'text-2xl md:text-[1.75rem] font-semibold leading-snug tracking-[-0.01em]',
  base: 'text-xl font-semibold tracking-[-0.01em]',
  sm:   'text-base font-semibold tracking-[-0.01em]',
}

interface HeadingProps {
  children: ReactNode
  level?: HeadingLevel
  size?: HeadingSize
  id?: string
  className?: string
}

export function Heading({
  children,
  level: Tag = 'h2',
  size = 'base',
  id,
  className = '',
}: HeadingProps) {
  return (
    <Tag
      id={id}
      className={`text-charcoal ${sizeClasses[size]} ${className}`}
    >
      {children}
    </Tag>
  )
}
