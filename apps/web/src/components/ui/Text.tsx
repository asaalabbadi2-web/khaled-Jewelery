import { type ReactNode } from 'react'

type TextVariant = 'body' | 'caption' | 'label' | 'mono'

const variantClasses: Record<TextVariant, string> = {
  body:    'text-base text-charcoal leading-relaxed',
  caption: 'text-sm text-charcoal/60 leading-normal',
  label:   'text-xs font-medium text-charcoal/70 uppercase tracking-wider',
  mono:    'text-sm font-mono tabular-nums text-charcoal',
}

interface TextProps {
  children: ReactNode
  variant?: TextVariant
  as?: keyof JSX.IntrinsicElements
  className?: string
}

export function Text({ children, variant = 'body', as: Tag = 'p', className = '' }: TextProps) {
  return (
    <Tag className={`${variantClasses[variant]} ${className}`}>
      {children}
    </Tag>
  )
}
