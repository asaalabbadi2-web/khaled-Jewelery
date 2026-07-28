'use client'

import { useState } from 'react'
import { COPY } from '@/lib/contract-copy'

interface Props {
  mainImg?:   string
  name:       string
  thumbnails: string[]
}

function GoldPlaceholder() {
  return (
    <div
      className="w-full h-full"
      style={{ background: 'linear-gradient(135deg, #c9a84c22 0%, #c9a84c55 100%)' }}
      aria-hidden="true"
    />
  )
}

export function ProductImageGallery({ mainImg, name, thumbnails }: Props) {
  const all    = [mainImg, ...thumbnails].filter((s): s is string => Boolean(s))
  const [selected, setSelected] = useState(0)
  const current = all[selected]

  return (
    <div className="flex flex-col gap-3">
      {/* Main image */}
      <div
        className="relative overflow-hidden rounded-sm bg-image-bg"
        style={{ aspectRatio: '4/5' }}
      >
        {current ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={current}
            alt={name}
            className="w-full h-full object-cover mix-blend-multiply"
          />
        ) : (
          <GoldPlaceholder />
        )}
      </div>

      {/* Thumbnails — only render when there are multiple images */}
      {all.length > 1 && (
        <div className="flex gap-2">
          {all.map((src, i) => (
            <button
              key={i}
              onClick={() => setSelected(i)}
              aria-label={i === 0 ? name : COPY.product.thumbnailAlt(i)}
              className={`relative overflow-hidden rounded-sm bg-image-bg flex-shrink-0 transition-opacity ${
                selected === i
                  ? 'ring-1 ring-gold opacity-100'
                  : 'opacity-50 hover:opacity-80'
              }`}
              style={{ width: 64, height: 80 }}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={src}
                alt=""
                aria-hidden="true"
                className="w-full h-full object-cover mix-blend-multiply"
              />
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
