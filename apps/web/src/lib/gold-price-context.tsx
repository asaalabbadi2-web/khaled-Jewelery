'use client'

/**
 * FC-6 single-source enforcement.
 * One age counter, one status derivation — feeds GoldLiveBar, PricingCard,
 * and availability logic from the same tick. No component derives its own age.
 */
import {
  createContext,
  useContext,
  useState,
  useEffect,
  type ReactNode,
} from 'react'
import { goldStatusFromAge, GoldPriceStatus } from './domain-states'
import { goldApi } from './api'
import type { GoldLiveBarRates } from '@/components/GoldLiveBar'

export interface GoldPriceState {
  rates: GoldLiveBarRates | null
  age: number
  status: GoldPriceStatus
  /** true when a HALTED system banner occupies the 40px slot below the bar */
  hasBanner: boolean
}

const GoldPriceCtx = createContext<GoldPriceState>({
  rates: null,
  age: 0,
  status: GoldPriceStatus.FRESH,
  hasBanner: false,
})

export function useGoldPrice(): GoldPriceState {
  return useContext(GoldPriceCtx)
}

interface GoldPriceProviderProps {
  /** Rates fetched server-side (may be null when SSR fetch fails in dev) */
  initialRates: GoldLiveBarRates | null
  /** Seconds since last update at SSR time */
  initialAge: number
  children: ReactNode
}

export function GoldPriceProvider({
  initialRates,
  initialAge,
  children,
}: GoldPriceProviderProps) {
  const [rates, setRates] = useState<GoldLiveBarRates | null>(initialRates)
  const [age, setAge]     = useState(initialAge)

  // Client-side fetch so MSW intercepts in dev (SSR fetch bypasses service worker).
  // On success, resets age to server-reported staleness.
  useEffect(() => {
    let cancelled = false
    goldApi.getRates()
      .then(data => {
        if (cancelled) return
        setRates({ karat24: data.karat24, karat21: data.karat21 })
        const serverAge = Math.max(
          0,
          Math.floor((Date.now() - new Date(data.updatedAt).getTime()) / 1_000),
        )
        setAge(serverAge)
      })
      .catch(() => { /* keep initial values — bar stays visible with no prices */ })
    return () => { cancelled = true }
  }, [])

  // Single tick — the only clock that increments age in this subtree.
  useEffect(() => {
    const id = window.setInterval(() => setAge(a => a + 1), 1_000)
    return () => window.clearInterval(id)
  }, [])

  const status    = goldStatusFromAge(age)
  const hasBanner = status === GoldPriceStatus.HALTED

  return (
    <GoldPriceCtx.Provider value={{ rates, age, status, hasBanner }}>
      {children}
    </GoldPriceCtx.Provider>
  )
}
