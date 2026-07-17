import { ImageWithFallback } from '@/components/ui'
import { COPY } from '@/lib/contract-copy'

export interface ProductImageProps {
  src?: string
  name: string
  /** Reduces saturation when reserved */
  reserved?: boolean
}

export function ProductImage({ src, name, reserved = false }: ProductImageProps) {
  return (
    <div
      className="relative overflow-hidden rounded-sm bg-image-bg mb-3"
      style={{ aspectRatio: '1/1' }}
    >
      <ImageWithFallback
        src={src}
        alt={name}
        forceFallback={!src}
        className={[
          'w-full h-full object-cover mix-blend-multiply transition-transform duration-300',
          'group-hover:scale-[1.04]',
          reserved ? 'saturate-50' : '',
        ].join(' ')}
      />
      {/* Hover overlay — shown via group-hover on the parent article */}
      <div className="absolute inset-x-0 bottom-0 flex justify-center pb-3 opacity-0 group-hover:opacity-100 transition-opacity duration-200">
        <span className="bg-charcoal/80 text-surface text-[10px] font-medium px-3 py-1 rounded-sm tracking-wide">
          {COPY.availability.viewOverlay}
        </span>
      </div>
    </div>
  )
}
