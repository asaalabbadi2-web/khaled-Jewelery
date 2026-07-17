import { type ReactNode } from 'react'

interface InlineProps {
  children: ReactNode
  gap?: number
  align?: 'start' | 'center' | 'end' | 'baseline'
  justify?: 'start' | 'center' | 'end' | 'between'
  className?: string
  as?: keyof JSX.IntrinsicElements
}

const alignClasses = {
  start:    'items-start',
  center:   'items-center',
  end:      'items-end',
  baseline: 'items-baseline',
}

const justifyClasses = {
  start:   'justify-start',
  center:  'justify-center',
  end:     'justify-end',
  between: 'justify-between',
}

export function Inline({
  children,
  gap = 2,
  align = 'center',
  justify = 'start',
  className = '',
  as: Tag = 'div',
}: InlineProps) {
  return (
    <Tag
      className={`flex flex-row gap-${gap} ${alignClasses[align]} ${justifyClasses[justify]} ${className}`}
    >
      {children}
    </Tag>
  )
}
