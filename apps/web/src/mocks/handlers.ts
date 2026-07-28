import { http, HttpResponse } from 'msw'
import { MOCK_CATALOG, getBreakdown } from './catalog-data'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api/v1'

// ── Reservation store (in-memory, keyed by reservationId) ────────────────────

interface ReservationRecord {
  itemId:      string
  itemName:    string
  lockedPrice: number
  expiresAt:   string
}

// RSV-SNAP is pre-seeded with an expired timestamp for the D1 snapshot test.
const reservationStore = new Map<string, ReservationRecord>([
  ['RSV-SNAP', {
    itemId:      'R-21-0342',
    itemName:    'خاتم سوليتير',
    lockedPrice: 1_215,
    expiresAt:   new Date(0).toISOString(), // epoch → always expired
  }],
])

let ridCounter = 1

export const handlers = [
  // Gold rates — serverNow is the current server time (FC-2); updatedAt is when
  // the price was last refreshed. In MSW both are ~now (price always fresh in dev).
  http.get(`${API_BASE}/catalog/gold-price`, () => {
    const now = new Date().toISOString()
    return HttpResponse.json({
      karat24:   330.15,
      karat21:   289.38,
      karat18:   248.02,
      updatedAt: now,
      serverNow: now,
    })
  }),

  // Catalog listing — path matches Commerce API /api/v1/catalog/products
  http.get(`${API_BASE}/catalog/products`, ({ request }) => {
    const q = new URL(request.url).searchParams.get('q')?.trim().toLowerCase() ?? ''
    const items = q ? MOCK_CATALOG.filter(p => p.name.includes(q)) : MOCK_CATALOG
    // Shape matches CatalogPageSchema
    const mapped = items.map(p => ({
      id:              p.id,
      item_code:       p.id,
      slug:            p.slug,
      name:            p.name,
      karat:           String(p.karat),
      weight:          p.weight,
      net_gold_weight: p.weight,
      has_stones:      false,
      stock:           p.availability === 'SOLD' ? 0 : 1,
      price:           p.price,
      category:        null,
    }))
    return HttpResponse.json({ items: mapped, total: mapped.length, page: 1, page_size: 20 })
  }),

  // Single product by slug — path matches Commerce API /api/v1/catalog/products/{slug}
  http.get(`${API_BASE}/catalog/products/:slug`, ({ params }) => {
    const item = MOCK_CATALOG.find(p => p.slug === params.slug)
    if (!item) return HttpResponse.json({ detail: 'not found' }, { status: 404 })
    return HttpResponse.json({
      id:              item.id,
      item_code:       item.id,
      slug:            item.slug,
      name:            item.name,
      karat:           String(item.karat),
      weight:          item.weight,
      net_gold_weight: item.weight,
      has_stones:      false,
      stock:           item.availability === 'SOLD' ? 0 : 1,
      price:           item.price,
      category:        null,
      pricing_snapshot: null,
    })
  }),

  // Create reservation — derives lockedPrice from the requested item (CRIT-1)
  // Accepts item_slug (real API contract) and falls back to itemId (legacy MSW).
  http.post(`${API_BASE}/reservations`, async ({ request }) => {
    const body = await request.json() as { item_slug?: string; itemId?: string }
    const slug = body.item_slug ?? body.itemId ?? ''
    const item = MOCK_CATALOG.find(p => p.slug === slug || p.id === slug)
    if (!item) return HttpResponse.json({ detail: 'item not found' }, { status: 404 })

    const reservationId = `RSV-${String(ridCounter++).padStart(3, '0')}`
    const expiresAt     = new Date(Date.now() + 10 * 60_000).toISOString()

    reservationStore.set(reservationId, {
      itemId:      item.slug,
      itemName:    item.name,
      lockedPrice: item.price,
      expiresAt,
    })

    return HttpResponse.json({ reservationId, lockedPrice: item.price, expiresAt })
  }),

  // Get reservation by rid — checkout reads only rid from URL (CRIT-2)
  // Response includes img + breakdown so the checkout summary can render the full quote.
  http.get(`${API_BASE}/reservations/:rid`, ({ params }) => {
    const record = reservationStore.get(params.rid as string)
    if (!record) return HttpResponse.json({ detail: 'not found' }, { status: 404 })
    const item = MOCK_CATALOG.find(p => p.id === record.itemId)
    return HttpResponse.json({
      reservationId: params.rid,
      ...record,
      img:       item?.img ?? '',
      breakdown: item ? getBreakdown(item.id, item) : [],
    })
  }),

  // Tracking — send OTP (returns masked phone for UI display)
  http.post(`${API_BASE}/tracking/send-otp`, () =>
    HttpResponse.json({ sent: true, maskedPhone: '5511' }),
  ),

  // Item availability — Gate B Frontend (PosAvailabilityGateConnected).
  // Default: available. Stories and integration tests override via per-handler MSW.
  // itemId is a numeric string in the URL path param.
  http.get(`${API_BASE}/catalog/items/:itemId/availability`, () =>
    HttpResponse.json({
      available:      true,
      reserved_until: null,
      reservation_id: null,
    }),
  ),

  // Tracking — verify OTP (only 123456 succeeds — A4)
  http.post(`${API_BASE}/tracking/verify-otp`, async ({ request }) => {
    const body = await request.json() as { code?: string }
    if (body.code !== '123456') {
      return HttpResponse.json({ detail: 'wrong code' }, { status: 400 })
    }
    return HttpResponse.json({
      orderId:        'ORD-5511',
      status:         'PREPARING',
      steps: [
        { label: 'تم الدفع',                        done: true,  active: false },
        { label: 'جارٍ تجهيز القطعة',               done: false, active: true  },
        { label: 'جُهّزت الشحنة (مؤمَّنة بالكامل)', done: false, active: false },
        { label: 'خرجت للتوصيل',                    done: false, active: false },
        { label: 'تم التسليم',                      done: false, active: false },
      ],
      carrierTrackNo: 'ARAMEX-9988',
      itemName:       'خاتم ذهب 24 قيراط',
      itemCode:       'RING24K001',
    })
  }),
]
