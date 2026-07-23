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
  karat24:   number
  karat21:   number
  karat18:   number
  updatedAt: string
  /** Current server timestamp — use with syncServerClock() for FC-2 compliance. */
  serverNow: string
}

export const goldApi = {
  getRates: () => apiFetch<GoldRates>('/catalog/gold-price'),
}

export interface CatalogItem {
  id:           string
  slug:         string
  name:         string
  karat:        18 | 21 | 24
  weight:       number
  price:        number
  availability: string
  img:          string
}

export const catalogApi = {
  search: (q: string) =>
    apiFetch<{ items: CatalogItem[]; total: number }>(
      q ? `/catalog/items?q=${encodeURIComponent(q)}` : '/catalog/items',
    ),
}

export interface ReservationResponse {
  reservationId: string
  lockedPrice:   number
  expiresAt:     string
}

export interface ReservationRecord {
  reservationId: string
  itemId:        string
  itemName:      string
  lockedPrice:   number
  expiresAt:     string
  img:           string
  breakdown:     Array<{ label: string; value: string }>
}

export const reservationApi = {
  create: (itemId: string) =>
    apiFetch<ReservationResponse>('/reservations', {
      method: 'POST',
      body:   JSON.stringify({ itemId }),
    }),
  get: (rid: string) =>
    apiFetch<ReservationRecord>(`/reservations/${rid}`),
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
  itemName:       string
  itemCode:       string
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

// ── Gate B: POS item availability ────────────────────────────────────────────
// Consumed by PosAvailabilityGateConnected (Gate B Frontend) and by the ERP
// backend (Gate B Backend, via services/commerce_availability.py).
// Scope: public / catalog-read — no auth required.

export interface ItemAvailabilityResponse {
  available:      boolean
  reserved_until: string | null
  reservation_id: string | null
}

export const availabilityApi = {
  check: (itemId: number) =>
    apiFetch<ItemAvailabilityResponse>(`/catalog/items/${itemId}/availability`),
}
