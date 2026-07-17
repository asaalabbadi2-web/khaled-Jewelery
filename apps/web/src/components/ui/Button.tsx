'use client'

import { type ReactNode, type ButtonHTMLAttributes } from 'react'

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'bronze' | 'outline'

const variantClasses: Record<ButtonVariant, string> = {
  primary:   'bg-gold text-white hover:bg-bronze active:bg-bronze/90',
  secondary: 'bg-charcoal/10 text-charcoal hover:bg-charcoal/15 active:bg-charcoal/20',
  ghost:     'bg-transparent text-charcoal hover:bg-charcoal/5 active:bg-charcoal/10',
  bronze:    [
    'bg-bronze text-surface font-semibold tracking-wide',
    'hover:bg-bronze-hover active:bg-bronze-hover/90 transition-colors duration-150',
    'disabled:bg-bronze/30 disabled:text-surface/50 disabled:cursor-not-allowed',
  ].join(' '),
  outline:   [
    'border border-gold/40 text-muted',
    'hover:bg-ivory transition-colors duration-150',
    'disabled:opacity-50 disabled:cursor-not-allowed',
  ].join(' '),
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode
  variant?: ButtonVariant
}

export function Button({ children, variant = 'primary', className = '', ...rest }: ButtonProps) {
  return (
    <button
      {...rest}
      className={[
        'inline-flex items-center justify-center gap-2',
        'py-3.5 px-4 rounded-sm text-sm',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold',
        variantClasses[variant],
        className,
      ].join(' ')}
    >
      {children}
    </button>
  )
}
