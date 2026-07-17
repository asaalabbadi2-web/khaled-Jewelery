/**
 * Typed API clients — all IO goes through here (FC policy).
 * No component calls fetch() directly.
 * MSW intercepts in dev/test; real Commerce API in production.
 */

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api/v1'

async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${path}`)
  }
  return res.json() as Promise<T>
}

export interface GoldRates {
  karat24: number
  karat21: number
  karat18: number
  updatedAt: string
}

export const goldApi = {
  getRates: () => apiFetch<GoldRates>('/catalog/gold-price'),
}
