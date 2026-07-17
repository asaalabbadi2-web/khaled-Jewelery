'use client'

import type { ReactNode } from 'react'
import { useGoldPrice } from '@/lib/gold-price-context'

/**
 * Applies top padding that matches the fixed chrome height:
 *   No banner:   bar(40px) + header(64px) = 104px  → pt-[104px]
 *   With banner: bar(40px) + banner(40px) + header(64px) = 144px → pt-36 (9rem)
 */
export function ContentOffset({ children }: { children: ReactNode }) {
  const { hasBanner } = useGoldPrice()
  return (
    <div className={`${hasBanner ? 'pt-36' : 'pt-[104px]'} min-h-screen`}>
      {children}
    </div>
  )
}
