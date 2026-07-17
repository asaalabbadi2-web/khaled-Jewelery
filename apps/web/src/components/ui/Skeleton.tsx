import { type CSSProperties } from 'react'

/**
 * FC-3 — Skeleton Contract.
 * Skeleton placeholders must match the exact dimensions of the live content.
 * Use the same className/style props you'd pass to the live element.
 */
interface SkeletonProps {
  className?: string
  style?: CSSProperties
}

export function Skeleton({ className = '', style }: SkeletonProps) {
  return (
    <div
      className={`animate-pulse bg-skeleton rounded-sm ${className}`}
      style={style}
      aria-hidden="true"
    />
  )
}
