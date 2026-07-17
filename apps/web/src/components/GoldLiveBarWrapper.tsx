'use client'

import { useState, useEffect } from 'react'
import { GoldLiveBar } from './GoldLiveBar'
import type { GoldLiveBarRates } from './GoldLiveBar'

export interface GoldLiveBarWrapperProps {
  rates: GoldLiveBarRates | null
  /** Age in seconds at SSR time — client timer increments from here */
  initialAge: number
  halted?: boolean
}

/** Client-side tick wrapper. Age starts at initialAge and increments every second. */
export function GoldLiveBarWrapper({ rates, initialAge, halted = false }: GoldLiveBarWrapperProps) {
  const [age, setAge] = useState(initialAge)

  useEffect(() => {
    const id = window.setInterval(() => setAge(a => a + 1), 1_000)
    return () => window.clearInterval(id)
  }, [])

  return <GoldLiveBar age={age} halted={halted} rates={rates} />
}
