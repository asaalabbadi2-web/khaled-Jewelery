'use client'

import { type ReactNode, type ButtonHTMLAttributes } from 'react'

type ButtonVariant = 'primary' | 'secondary' | 'ghost'

const variantClasses: Record<ButtonVariant, string> = {
  primary:   'bg-gold text-white hover:bg-bronze active:bg-bronze/90',
  secondary: 'bg-charcoal/10 text-charcoal hover:bg-charcoal/15 active:bg-charcoal/20',
  ghost:     'bg-transparent text-charcoal hover:bg-charcoal/5 active:bg-charcoal/10',
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode
  variant?: ButtonVariant
}

export function Button({ children, variant = 'primary', className = '', ...rest }: ButtonProps) {
  return (
    <button
      {...rest}
      className={`
        inline-flex items-center justify-center gap-2
        px-4 py-2 rounded-lg text-sm font-medium
        transition-colors duration-150
        focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold focus-visible:ring-offset-2
        disabled:opacity-50 disabled:pointer-events-none
        ${variantClasses[variant]} ${className}
      `}
    >
      {children}
    </button>
  )
}
