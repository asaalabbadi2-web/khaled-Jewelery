'use client'

import { useState, type ImgHTMLAttributes } from 'react'

/**
 * Image with a designed gold-diamond fallback.
 * Rebuilt from the pattern found inline in 3+ design-reference pages (R4).
 * Use this everywhere — never inline the fallback logic again.
 */
interface ImageWithFallbackProps extends ImgHTMLAttributes<HTMLImageElement> {
  /** Force the fallback state (useful for Storybook stories). */
  forceFallback?: boolean
  /** Extra classes applied to the fallback wrapper <div>. */
  fallbackClassName?: string
}

export function ImageWithFallback({
  src,
  alt = '',
  className = '',
  style,
  forceFallback = false,
  fallbackClassName = '',
  ...rest
}: ImageWithFallbackProps) {
  const [failed, setFailed] = useState(false)

  if (failed || forceFallback) {
    return (
      <div
        className={`w-full h-full flex items-center justify-center bg-image-bg ${fallbackClassName || className}`}
        style={style}
        aria-hidden="true"
      >
        <span className="text-gold/50 text-2xl select-none">◇</span>
      </div>
    )
  }

  return (
    <img
      src={src}
      alt={alt}
      className={className}
      style={style}
      onError={() => setFailed(true)}
      {...rest}
    />
  )
}
