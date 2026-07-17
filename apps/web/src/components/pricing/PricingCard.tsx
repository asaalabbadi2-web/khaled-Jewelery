import { Lock, CheckCircle, WifiOff } from 'lucide-react'
import { GoldPriceStatus } from '@/lib/domain-states'
import { RESERVATION_MS } from '@/lib/server-clock'
import { pr } from '@/lib/format'
import { COPY } from '@/lib/contract-copy'
import { Skeleton } from '@/components/ui'
import { PriceHeader } from './PriceHeader'
import { GoldBreakdown } from './GoldBreakdown'
import { LiveStatus } from './LiveStatus'
import { CountdownBlock } from './CountdownBlock'
import { PriceActions } from './PriceActions'
import type { BreakdownLine } from './GoldBreakdown'

// UI state for the PricingCard — distinct from domain-states because it includes
// transient UI states (SKELETON, OFFLINE) that do not exist in the domain layer.
export type PricingState =
  | 'DEFAULT' | 'RESERVED' | 'EXPIRED' | 'STALE' | 'HALTED'
  | 'RESERVED_BY_OTHER' | 'RACE_CONFLICT' | 'SOLD'
  | 'PAYMENT_VERIFYING' | 'LATE_PAYMENT' | 'REFUNDED'
  | 'OFFLINE' | 'SKELETON'

export interface PricingCardProps {
  state: PricingState
  price?: number
  priceNew?: number
  /** Remaining reservation milliseconds (RESERVED / OFFLINE states) */
  ms?: number
  /** Seconds since last rate update (DEFAULT state freshness indicator) */
  ageSeconds?: number
  breakdownItems?: BreakdownLine[]
  onReserve?(): void
  onCancel?(): void
  onReserveNew?(): void
  onCheckout?(): void
  onBrowse?(): void
  /** Live gold price status from context — feeds LiveStatus in DEFAULT branch (FC-6) */
  goldStatus?: GoldPriceStatus
}

type CardBorder = 'active' | 'expired' | 'stale' | 'default'

const borderClass: Record<CardBorder, string> = {
  active:  'border-gold/55',
  expired: 'border-muted/50',
  stale:   'border-muted/50 saturate-90',
  default: 'border-muted/30',
}

// composition-only — renders sub-components by state; zero own styling except the card shell
export function PricingCard({
  state,
  price = 0,
  priceNew,
  ms = 0,
  ageSeconds = 0,
  breakdownItems = [],
  onReserve,
  onCancel,
  onReserveNew,
  onCheckout,
  onBrowse,
  goldStatus = GoldPriceStatus.FRESH,
}: PricingCardProps) {
  const border: CardBorder =
    state === 'RESERVED' || state === 'OFFLINE' ? 'active'  :
    state === 'EXPIRED'                          ? 'expired' :
    state === 'STALE'   || state === 'HALTED'   ? 'stale'   :
                                                   'default'

  const card = `relative rounded-sm border bg-surface p-5 md:p-6 ${borderClass[border]}`

  /* ── Badge (absolute top-left corner) ── */
  const badge =
    state === 'RESERVED' || state === 'OFFLINE' ? (
      <span
        className="absolute top-3 left-3 grid h-5 w-5 place-items-center rounded-full border border-gold/45 bg-surface text-bronze"
        aria-label="محجوز"
      >
        <Lock size={10} aria-hidden="true" />
      </span>
    ) : state === 'EXPIRED' ? (
      <span className="absolute top-3 left-3 h-2 w-2 rounded-full bg-muted-2" aria-hidden="true" />
    ) : state === 'STALE' || state === 'HALTED' ? (
      <span className="absolute top-3 left-3 h-2 w-2 rounded-full bg-warning" aria-hidden="true" />
    ) : null

  /* ─────────────── SKELETON ─────────────── */
  if (state === 'SKELETON') {
    return (
      <div className={card}>
        <Skeleton className="h-3 w-20 mb-2" />
        <Skeleton className="h-11 w-40 mb-4" />
        <Skeleton className="h-3 w-32 mb-5" />
        <Skeleton className="h-12 w-full mb-2" />
        <Skeleton className="h-3 w-44 mx-auto" />
      </div>
    )
  }

  /* ─────────────── DEFAULT ─────────────── */
  if (state === 'DEFAULT') {
    return (
      <div className={card}>
        {badge}
        <PriceHeader price={price} />
        {breakdownItems.length > 0 && <GoldBreakdown items={breakdownItems} />}
        <LiveStatus status={goldStatus} ageSeconds={ageSeconds} />
        <PriceActions variant="reserve" onReserve={onReserve} />
      </div>
    )
  }

  /* ─────────────── RESERVED ─────────────── */
  if (state === 'RESERVED') {
    return (
      <div className={card}>
        {badge}
        <div className="flex items-center gap-2 text-success text-sm font-medium mb-4">
          <CheckCircle size={14} aria-hidden="true" />
          {COPY.pricing.reserved}
        </div>
        <div className="flex items-center gap-2 mb-5">
          <Lock size={12} className="text-gold shrink-0" aria-hidden="true" />
          <span dir="ltr" className="text-charcoal text-2xl font-semibold tabular-nums">
            {pr(price)}
          </span>
          <span className="text-muted text-sm">ر.س</span>
          <span className="text-muted text-xs">{COPY.pricing.priceLocked}</span>
        </div>
        <CountdownBlock ms={ms} reservationMs={RESERVATION_MS} />
        <PriceActions variant="checkout" onCheckout={onCheckout} onCancel={onCancel} />
      </div>
    )
  }

  /* ─────────────── EXPIRED ─────────────── */
  if (state === 'EXPIRED') {
    return (
      <div className={card}>
        {badge}
        <p className="text-charcoal font-semibold mb-4">{COPY.pricing.expiredTitle}</p>
        <div className="rounded-sm bg-ivory border border-muted/30 p-3 mb-5 text-sm space-y-2">
          <div className="flex justify-between">
            <span className="text-charcoal/75 font-medium">{COPY.pricing.prevPrice}</span>
            <span dir="ltr" className="tabular-nums text-charcoal/75 font-medium">
              {pr(price)} {COPY.pricing.priceUnit}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-charcoal/75 font-medium">{COPY.pricing.newPrice}</span>
            <span dir="ltr" className="tabular-nums text-charcoal/75 font-medium">
              {pr(priceNew ?? price)} {COPY.pricing.priceUnit}
            </span>
          </div>
        </div>
        <PriceActions variant="reserve-new" onReserveNew={onReserveNew} onCancel={onCancel} />
      </div>
    )
  }

  /* ─────────────── STALE ─────────────── */
  if (state === 'STALE') {
    return (
      <div className={card}>
        {badge}
        <PriceHeader price={price} dimmed />
        <LiveStatus status={GoldPriceStatus.STALE} />
        <PriceActions variant="disabled-stale" />
      </div>
    )
  }

  /* ─────────────── HALTED ─────────────── */
  if (state === 'HALTED') {
    return (
      <div className={card}>
        {badge}
        <LiveStatus status={GoldPriceStatus.HALTED} />
        <PriceActions variant="disabled-halted" />
      </div>
    )
  }

  /* ─────────────── RESERVED_BY_OTHER ─────────────── */
  if (state === 'RESERVED_BY_OTHER') {
    return (
      <div className={card}>
        {badge}
        <p className="text-charcoal font-semibold mb-2">{COPY.pricing.reservedByOther}</p>
        <p className="text-muted text-sm leading-relaxed mb-5">{COPY.pricing.reservedByOtherSub}</p>
        <PriceActions variant="browse" onBrowse={onBrowse} />
      </div>
    )
  }

  /* ─────────────── RACE_CONFLICT ─────────────── */
  if (state === 'RACE_CONFLICT') {
    return (
      <div className={card}>
        {badge}
        <PriceHeader price={price} />
        <div className="rounded-sm bg-ivory border border-gold/20 px-3 py-3 mb-4">
          <p className="text-muted text-sm leading-relaxed">
            {COPY.pricing.raceConflict}
          </p>
        </div>
        <PriceActions variant="browse" onBrowse={onBrowse} />
      </div>
    )
  }

  /* ─────────────── SOLD ─────────────── */
  if (state === 'SOLD') {
    return (
      <div className={card}>
        {badge}
        <p className="text-charcoal font-semibold mb-2">{COPY.pricing.soldTitle}</p>
        <p className="text-muted text-sm leading-relaxed mb-5">{COPY.pricing.soldSub}</p>
        <PriceActions variant="browse" onBrowse={onBrowse} />
      </div>
    )
  }

  /* ─────────────── PAYMENT_VERIFYING ─────────────── */
  if (state === 'PAYMENT_VERIFYING') {
    return (
      <div className={`${card} flex flex-col items-center py-8`}>
        {badge}
        <div
          className="w-9 h-9 rounded-full border-2 border-gold/20 border-t-gold animate-spin mb-5"
          aria-hidden="true"
        />
        <p className="text-charcoal font-semibold mb-2">{COPY.pricing.verifyingTitle}</p>
        <p className="text-muted text-xs text-center leading-relaxed max-w-[18rem]">
          {COPY.pricing.verifyingNote}
        </p>
      </div>
    )
  }

  /* ─────────────── LATE_PAYMENT ─────────────── */
  if (state === 'LATE_PAYMENT') {
    return (
      <div className={card}>
        {badge}
        <p className="text-charcoal font-semibold mb-3">{COPY.pricing.latePaymentTitle}</p>
        <p className="text-muted text-sm leading-relaxed">{COPY.pricing.latePaymentNote}</p>
      </div>
    )
  }

  /* ─────────────── REFUNDED ─────────────── */
  if (state === 'REFUNDED') {
    return (
      <div className={card}>
        {badge}
        <div className="flex items-center gap-2 text-success font-medium mb-3">
          <CheckCircle size={14} aria-hidden="true" />
          {COPY.pricing.refundedTitle}
        </div>
        <p className="text-muted text-sm leading-relaxed mb-5">{COPY.pricing.refundedNote}</p>
        <PriceActions variant="browse" onBrowse={onBrowse} />
      </div>
    )
  }

  /* ─────────────── OFFLINE ─────────────── */
  if (state === 'OFFLINE') {
    return (
      <div className={card}>
        {badge}
        <div className="flex items-center gap-2 text-success text-sm font-medium mb-4">
          <CheckCircle size={14} aria-hidden="true" />
          {COPY.pricing.reserved}
        </div>
        <div className="flex items-center gap-2 mb-5">
          <Lock size={12} className="text-gold shrink-0" aria-hidden="true" />
          <span dir="ltr" className="text-charcoal text-2xl font-semibold tabular-nums">
            {pr(price)}
          </span>
          <span className="text-muted text-sm">ر.س {COPY.pricing.priceLocked}</span>
        </div>
        <CountdownBlock ms={ms} reservationMs={RESERVATION_MS} frozen />
        <div className="flex items-start gap-2 bg-warning/[0.07] border border-warning/25 rounded-sm px-3 py-2.5 mb-4">
          <WifiOff size={13} className="text-warning mt-0.5 shrink-0" aria-hidden="true" />
          <p className="text-warning text-xs leading-relaxed">{COPY.pricing.offlineNote}</p>
        </div>
        <PriceActions variant="disabled-checkout" />
      </div>
    )
  }

  return null
}
