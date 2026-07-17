import { type ReactNode } from 'react'

type BadgeVariant = 'neutral' | 'success' | 'warning' | 'muted'

const variantClasses: Record<BadgeVariant, string> = {
  neutral: 'bg-charcoal/10 text-charcoal',
  success: 'bg-success/15 text-success',
  warning: 'bg-warning/15 text-warning',
  muted:   'bg-charcoal/5 text-charcoal/50',
}

interface BadgeProps {
  children: ReactNode
  variant?: BadgeVariant
  className?: string
}

export function Badge({ children, variant = 'neutral', className = '' }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${variantClasses[variant]} ${className}`}
    >
      {children}
    </span>
  )
}
