'use client'

import { goldStatusFromAge, GoldPriceStatus } from '@/lib/domain-states'
import { COPY } from '@/lib/contract-copy'
import { pr } from '@/lib/format'

export interface GoldLiveBarRates {
  karat24: number
  karat21: number
}

export interface GoldLiveBarProps {
  /** Seconds elapsed since the last successful rate update. */
  age: number
  /** Provider explicitly signalled halt (no fetch possible). */
  halted?: boolean
  /** Live rates from API; omit or pass null to hide price columns. */
  rates?: GoldLiveBarRates | null
}

// R1: status derived exclusively from domain function — not recomputed here.
export function GoldLiveBar({ age, halted = false, rates = null }: GoldLiveBarProps) {
  const status  = goldStatusFromAge(age, halted)
  const stale   = status !== GoldPriceStatus.FRESH
  const loading = rates === null

  return (
    <div
      className="fixed top-0 inset-x-0 h-10 z-50 bg-charcoal flex items-center justify-center gap-5 px-4 text-xs"
      role="banner"
      aria-label={COPY.goldBar.ariaLabel}
    >
      {/* 24K price — always rendered; shows placeholder dash while loading */}
      <span className="flex items-center gap-1.5">
        <span className="text-muted">24K</span>
        <span dir="ltr" className={`tabular-nums font-medium ${loading ? 'text-muted-2' : 'text-ivory/90'}`}>
          {loading ? '—' : pr(rates!.karat24)}
        </span>
        <span className="text-muted">{COPY.goldBar.perGram}</span>
      </span>

      <span className="text-gold/30 hidden sm:inline" aria-hidden="true">·</span>

      {/* 21K — hidden on mobile */}
      <span className="hidden sm:flex items-center gap-1.5">
        <span className="text-muted">21K</span>
        <span dir="ltr" className={`tabular-nums font-medium ${loading ? 'text-muted-2' : 'text-ivory/90'}`}>
          {loading ? '—' : pr(rates!.karat21)}
        </span>
        <span className="text-muted">{COPY.goldBar.perGram}</span>
      </span>

      <span className="text-gold/30 hidden md:inline" aria-hidden="true">·</span>

      {/* Freshness indicator — hidden on small screens */}
      {stale ? (
        <span className="hidden md:flex items-center gap-1.5" aria-live="polite">
          <span
            className="w-1.5 h-1.5 rounded-full bg-warning animate-pulse inline-block shrink-0"
            aria-hidden="true"
          />
          <span className="text-warning">{COPY.goldBar.updating}</span>
        </span>
      ) : (
        <span className="hidden md:flex items-center gap-1.5">
          <span
            className="w-1.5 h-1.5 rounded-full bg-success animate-pulse inline-block shrink-0"
            aria-hidden="true"
          />
          <span className="text-muted">{COPY.goldBar.lastUpdatedPrefix}</span>
          <span dir="ltr" className="tabular-nums text-muted-2">{age}</span>
          <span className="text-muted">{COPY.goldBar.lastUpdatedSuffix}</span>
        </span>
      )}
    </div>
  )
}
