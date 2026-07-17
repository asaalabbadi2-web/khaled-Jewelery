import { http, HttpResponse } from 'msw'
import { MOCK_CATALOG, getBreakdown } from './catalog-data'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api/v1'

export const handlers = [
  // Gold rates
  http.get(`${API_BASE}/catalog/gold-price`, () =>
    HttpResponse.json({
      karat24:   330.15,
      karat21:   289.38,
      karat18:   248.02,
      updatedAt: new Date().toISOString(),
    }),
  ),

  // Catalog listing
  http.get(`${API_BASE}/catalog/items`, () =>
    HttpResponse.json({ items: MOCK_CATALOG, total: MOCK_CATALOG.length }),
  ),

  // Single product by slug — uses shared MOCK_CATALOG (A3: no standalone mock)
  http.get(`${API_BASE}/catalog/items/:slug`, ({ params }) => {
    const item = MOCK_CATALOG.find(p => p.slug === params.slug)
    if (!item) return HttpResponse.json({ detail: 'not found' }, { status: 404 })
    return HttpResponse.json({ ...item, breakdown: getBreakdown(item.id, item) })
  }),

  // Create reservation
  http.post(`${API_BASE}/reservations`, () =>
    HttpResponse.json({
      reservationId: 'RSV-001',
      lockedPrice:   1_214.69,
      expiresAt:     new Date(Date.now() + 10 * 60_000).toISOString(),
    }),
  ),

  // Tracking — send OTP (returns masked phone for UI display)
  http.post(`${API_BASE}/tracking/send-otp`, () =>
    HttpResponse.json({ sent: true, maskedPhone: '5511' }),
  ),

  // Tracking — verify OTP (only 123456 succeeds — A4)
  http.post(`${API_BASE}/tracking/verify-otp`, async ({ request }) => {
    const body = await request.json() as { code?: string }
    if (body.code !== '123456') {
      return HttpResponse.json({ detail: 'wrong code' }, { status: 400 })
    }
    return HttpResponse.json({
      orderId: 'ORD-5511',
      status:  'PREPARING',
      steps: [
        { label: 'تم الدفع',                        done: true,  active: false },
        { label: 'جارٍ تجهيز القطعة',               done: false, active: true  },
        { label: 'جُهّزت الشحنة (مؤمَّنة بالكامل)', done: false, active: false },
        { label: 'خرجت للتوصيل',                    done: false, active: false },
        { label: 'تم التسليم',                      done: false, active: false },
      ],
      carrierTrackNo: 'ARAMEX-9988',
    })
  }),
]
