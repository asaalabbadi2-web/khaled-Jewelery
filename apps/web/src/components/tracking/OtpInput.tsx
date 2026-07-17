'use client'

import { useState, useRef } from 'react'
import { COPY } from '@/lib/contract-copy'

export interface OtpInputProps {
  onComplete(code: string): void
}

const DIGITS = 6

export function OtpInput({ onComplete }: OtpInputProps) {
  const [digits, setDigits] = useState<string[]>(Array(DIGITS).fill(''))
  const refs = useRef<(HTMLInputElement | null)[]>([])

  const setAt = (index: number, value: string) => {
    const cleaned = value.replace(/\D/g, '')

    // Handle paste: distribute across all inputs
    if (cleaned.length > 1) {
      const next = [...digits]
      cleaned.slice(0, DIGITS).split('').forEach((d, i) => { next[i] = d })
      setDigits(next)
      refs.current[Math.min(cleaned.length, DIGITS - 1)]?.focus()
      if (cleaned.length >= DIGITS) onComplete(cleaned.slice(0, DIGITS))
      return
    }

    const next = [...digits]
    next[index] = cleaned
    setDigits(next)
    if (cleaned && index < DIGITS - 1) refs.current[index + 1]?.focus()
    if (cleaned && index === DIGITS - 1 && next.every(Boolean)) onComplete(next.join(''))
  }

  return (
    <div className="flex gap-2 justify-center" dir="ltr">
      {digits.map((digit, index) => (
        <input
          key={index}
          ref={el => { refs.current[index] = el }}
          value={digit}
          inputMode="numeric"
          maxLength={DIGITS}
          aria-label={COPY.tracking.otpDigitLabel(index + 1)}
          onChange={e => setAt(index, e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Backspace' && !digits[index] && index > 0) {
              refs.current[index - 1]?.focus()
            }
          }}
          className={[
            'h-11 w-10 rounded-sm text-center text-lg tabular-nums',
            'border border-gold/30 bg-surface',
            'focus:outline-none focus:border-gold focus:ring-1 focus:ring-gold/30',
          ].join(' ')}
        />
      ))}
    </div>
  )
}
