'use client'

import { GoldPriceStatus } from '@/lib/domain-states'
import { goldLiveBar } from '@/lib/contract-copy'
import { Badge, Inline, Text } from '@/components/ui'

export interface GoldLiveBarProps {
  /** null = rates fetch failed → HALTED */
  ageSeconds: number | null
}

function deriveStatus(ageSeconds: number | null): GoldPriceStatus {
  if (ageSeconds === null) return GoldPriceStatus.HALTED
  if (ageSeconds > 120) return GoldPriceStatus.STALE
  return GoldPriceStatus.FRESH
}

function statusBadge(status: GoldPriceStatus, ageSeconds: number | null) {
  switch (status) {
    case GoldPriceStatus.FRESH:
      return (
        <Badge variant="success">
          {goldLiveBar.fresh(ageSeconds!)}
        </Badge>
      )
    case GoldPriceStatus.STALE:
      return <Badge variant="warning">{goldLiveBar.stale}</Badge>
    case GoldPriceStatus.HALTED:
      return <Badge variant="muted">{goldLiveBar.halted}</Badge>
  }
}

export function GoldLiveBar({ ageSeconds }: GoldLiveBarProps) {
  const status = deriveStatus(ageSeconds)

  return (
    <div
      role="status"
      aria-live="polite"
      aria-label="حالة تحديث أسعار الذهب"
      className="h-10 w-full bg-surface border-b border-charcoal/10 flex items-center px-4"
    >
      <Inline gap={2} align="center">
        <span className="w-2 h-2 rounded-full bg-gold shrink-0" aria-hidden="true" />
        {statusBadge(status, ageSeconds)}
        {status === GoldPriceStatus.STALE && (
          <Text variant="caption" as="span" className="animate-pulse">
            ●
          </Text>
        )}
      </Inline>
    </div>
  )
}
