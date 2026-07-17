import { ItemAvailability } from '@/lib/domain-states'
import { COPY } from '@/lib/contract-copy'

export interface ProductAvailabilityBadgeProps {
  availability: ItemAvailability
}

export function ProductAvailabilityBadge({ availability }: ProductAvailabilityBadgeProps) {
  if (availability === ItemAvailability.RESERVED) {
    return (
      <div className="flex items-center gap-1.5 mt-1.5">
        <span className="text-warning text-xs select-none" aria-hidden="true">◐</span>
        <span className="text-warning text-xs">{COPY.availability.reservedByOther}</span>
      </div>
    )
  }

  if (availability === ItemAvailability.SOLD) {
    return (
      <div className="flex items-center gap-1.5 mt-1.5">
        <span className="w-1.5 h-1.5 rounded-full bg-error shrink-0" aria-hidden="true" />
        <span className="text-error text-xs">{COPY.availability.sold}</span>
      </div>
    )
  }

  // AVAILABLE
  return (
    <div className="flex items-center gap-1.5 mt-1.5">
      <span className="w-1.5 h-1.5 rounded-full bg-success shrink-0" aria-hidden="true" />
      <span className="text-success text-xs">{COPY.availability.available}</span>
    </div>
  )
}
