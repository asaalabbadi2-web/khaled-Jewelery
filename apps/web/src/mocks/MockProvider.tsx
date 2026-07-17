'use client'

import { useEffect, type ReactNode } from 'react'

/** Starts the MSW service worker in development only. Renders children immediately
 *  so the UI isn't blocked — handlers kick in within the first request cycle. */
export function MockProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    if (process.env.NODE_ENV !== 'development') return
    import('./browser').then(({ worker }) => {
      worker.start({ onUnhandledRequest: 'bypass' })
    })
  }, [])

  return <>{children}</>
}
