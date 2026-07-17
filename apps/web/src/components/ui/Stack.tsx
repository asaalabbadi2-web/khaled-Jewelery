import { type ReactNode } from 'react'

interface StackProps {
  children: ReactNode
  gap?: number
  className?: string
  as?: keyof JSX.IntrinsicElements
}

export function Stack({ children, gap = 4, className = '', as: Tag = 'div' }: StackProps) {
  return (
    <Tag className={`flex flex-col gap-${gap} ${className}`}>
      {children}
    </Tag>
  )
}
