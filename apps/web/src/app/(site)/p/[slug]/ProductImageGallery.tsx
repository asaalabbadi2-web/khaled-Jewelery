'use client'

import { useState } from 'react'
import { COPY } from '@/lib/contract-copy'

interface Props {
  mainImg:    string
  name:       string
  thumbnails: string[]
}

export function ProductImageGallery({ mainImg, name, thumbnails }: Props) {
  const all = [mainImg, ...thumbnails]
  const [selected, setSelected] = useState(0)

  return (
    <div className="flex flex-col gap-3">
      {/* Main image */}
      <div
        className="relative overflow-hidden rounded-sm bg-image-bg"
        style={{ aspectRatio: '4/5' }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={all[selected]}
          alt={name}
          className="w-full h-full object-cover mix-blend-multiply"
        />
      </div>

      {/* Thumbnails */}
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
    </div>
  )
}
