import { type ReactNode } from 'react'

interface SurfaceProps {
  children: ReactNode
  className?: string
  as?: keyof JSX.IntrinsicElements
}

export function Surface({ children, className = '', as: Tag = 'div' }: SurfaceProps) {
  return (
    <Tag className={`bg-surface rounded-lg ${className}`}>
      {children}
    </Tag>
  )
}
