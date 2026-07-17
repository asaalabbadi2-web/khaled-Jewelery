import { http, HttpResponse } from 'msw'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api/v1'

export const handlers = [
  http.get(`${API_BASE}/catalog/gold-price`, () =>
    HttpResponse.json({
      karat24: 285.50,
      karat21: 249.81,
      karat18: 214.13,
      updatedAt: new Date().toISOString(),
    }),
  ),
]
