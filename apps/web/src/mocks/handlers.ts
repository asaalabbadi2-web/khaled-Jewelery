import { http, HttpResponse } from 'msw'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api/v1'

const MOCK_CATALOG = [
  { id: 'R-21-0342', slug: 'R-21-0342', name: 'خاتم سوليتير',  karat: 21, weight: 8.45,  price: 1_215.00, availability: 'AVAILABLE', img: 'https://images.unsplash.com/photo-1605100804763-247f67b3557e?w=600&h=600&fit=crop&auto=format' },
  { id: 'R-21-0418', slug: 'R-21-0418', name: 'خاتم تريلوجي',  karat: 21, weight: 9.30,  price: 2_340.00, availability: 'RESERVED',  img: 'https://images.unsplash.com/photo-1589128777073-263566ae5e4d?w=600&h=600&fit=crop&auto=format' },
  { id: 'R-18-0314', slug: 'R-18-0314', name: 'خاتم هالو',      karat: 18, weight: 5.60,  price: 1_480.00, availability: 'AVAILABLE', img: 'https://images.unsplash.com/photo-1598560917807-1bae44bd2be8?w=600&h=600&fit=crop&auto=format' },
  { id: 'R-21-0385', slug: 'R-21-0385', name: 'خاتم بافلي',     karat: 21, weight: 7.20,  price: 1_651.00, availability: 'AVAILABLE', img: 'https://images.unsplash.com/photo-1611955167811-4711904bb9f8?w=600&h=600&fit=crop&auto=format' },
  { id: 'R-21-0466', slug: 'R-21-0466', name: 'خاتم فينيتاج',   karat: 21, weight: 11.80, price: 3_050.00, availability: 'AVAILABLE', img: 'https://images.unsplash.com/photo-1602173574767-37ac01994b2a?w=600&h=600&fit=crop&auto=format' },
  { id: 'R-21-0399', slug: 'R-21-0399', name: 'خاتم كلاسيك',    karat: 21, weight: 7.80,  price: 1_790.00, availability: 'AVAILABLE', img: 'https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=600&h=600&fit=crop&auto=format' },
]

export const handlers = [
  // Gold rates
  http.get(`${API_BASE}/catalog/gold-price`, () =>
    HttpResponse.json({
      karat24: 330.15,
      karat21: 289.38,
      karat18: 248.02,
      updatedAt: new Date().toISOString(),
    }),
  ),

  // Catalog listing (by category)
  http.get(`${API_BASE}/catalog/items`, () =>
    HttpResponse.json({ items: MOCK_CATALOG, total: MOCK_CATALOG.length }),
  ),

  // Single product by slug
  http.get(`${API_BASE}/catalog/items/:slug`, ({ params }) => {
    const item = MOCK_CATALOG.find(p => p.slug === params.slug)
    if (!item) return HttpResponse.json({ detail: 'not found' }, { status: 404 })
    return HttpResponse.json({
      ...item,
      breakdown: [
        { label: 'مكوّن الذهب (8.450غ × 289.40)', value: 2_445.43 },
        { label: 'المصنعية',                        value: 350.00 },
        { label: 'الأحجار',                         value: 220.00 },
        { label: 'الضريبة (15%)',                   value: 452.31 },
      ],
    })
  }),

  // Create reservation
  http.post(`${API_BASE}/reservations`, () =>
    HttpResponse.json({
      reservationId: 'RSV-001',
      lockedPrice:   1_214.69,
      expiresAt:     new Date(Date.now() + 10 * 60_000).toISOString(),
    }),
  ),

  // Tracking — send OTP
  http.post(`${API_BASE}/tracking/send-otp`, () =>
    HttpResponse.json({ sent: true }),
  ),

  // Tracking — verify OTP
  http.post(`${API_BASE}/tracking/verify-otp`, () =>
    HttpResponse.json({
      orderId: 'ORD-5511',
      status:  'PREPARING',
      steps: [
        { label: 'تم الدفع',                              done: true,  active: false },
        { label: 'جارٍ تجهيز القطعة',                     done: false, active: true  },
        { label: 'جُهّزت الشحنة (مؤمَّنة بالكامل)',       done: false, active: false },
        { label: 'خرجت للتوصيل',                           done: false, active: false },
        { label: 'تم التسليم',                             done: false, active: false },
      ],
    }),
  ),
]
