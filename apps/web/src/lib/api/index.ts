/**
 * Typed API clients — all IO goes through here (FC policy).
 * No component calls fetch() directly.
 * MSW intercepts in dev/test; real Commerce API in production.
 */

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api/v1'

export class ApiError extends Error {
  constructor(public readonly status: number, path: string) {
    super(`API ${status}: ${path}`)
    this.name = 'ApiError'
  }
}

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
  if (!res.ok) throw new ApiError(res.status, path)
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

export interface ReservationResponse {
  reservationId: string
  lockedPrice:   number
  expiresAt:     string
}

export const reservationApi = {
  create: (itemId: string) =>
    apiFetch<ReservationResponse>('/reservations', {
      method: 'POST',
      body:   JSON.stringify({ itemId }),
    }),
}

export interface SendOtpResponse {
  sent:        boolean
  maskedPhone: string
}

export interface VerifyOtpResponse {
  orderId:        string
  status:         string
  steps:          Array<{ label: string; done: boolean; active: boolean }>
  carrierTrackNo: string
}

export const trackingApi = {
  sendOtp: (orderNumber: string) =>
    apiFetch<SendOtpResponse>('/tracking/send-otp', {
      method: 'POST',
      body:   JSON.stringify({ orderNumber }),
    }),
  verifyOtp: (orderNumber: string, code: string) =>
    apiFetch<VerifyOtpResponse>('/tracking/verify-otp', {
      method: 'POST',
      body:   JSON.stringify({ orderNumber, code }),
    }),
}
