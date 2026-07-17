import { Skeleton } from '@/components/ui'

/** FC-3: skeleton must match ProductCard dimensions. */
export function SkeletonCard() {
  return (
    <div aria-hidden="true">
      <Skeleton style={{ aspectRatio: '1/1' }} className="mb-3" />
      <Skeleton className="h-3.5 w-3/4 mb-1.5" />
      <Skeleton className="h-3 w-1/2 mb-2" />
      <Skeleton className="h-3.5 w-2/5" />
    </div>
  )
}
