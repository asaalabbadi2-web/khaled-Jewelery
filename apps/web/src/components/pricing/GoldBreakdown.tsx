'use client'

import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { COPY } from '@/lib/contract-copy'

export interface BreakdownLine {
  label: string
  value: string
}

export interface GoldBreakdownProps {
  items: BreakdownLine[]
}

export function GoldBreakdown({ items }: GoldBreakdownProps) {
  const [open, setOpen] = useState(false)

  return (
    <>
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1 text-bronze text-xs mb-3 hover:opacity-70 transition-opacity"
        aria-expanded={open}
        aria-controls="price-breakdown"
      >
        {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        {COPY.pricing.priceDetails}
      </button>

      {open && (
        <div
          id="price-breakdown"
          className="mb-4 rounded-sm bg-ivory border border-gold/20 p-3 text-xs space-y-2"
        >
          {items.map(({ label, value }) => (
            <div key={label} className="flex justify-between">
              <span className="text-muted">{label}</span>
              <span dir="ltr" className="tabular-nums text-charcoal">{value} {COPY.pricing.priceUnit}</span>
            </div>
          ))}
        </div>
      )}
    </>
  )
}
