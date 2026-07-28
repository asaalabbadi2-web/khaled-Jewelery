/**
 * Server-side Commerce API fetch utilities (React Server Components only).
 *
 * Uses COMMERCE_API_URL (server-only env var — no NEXT_PUBLIC_ prefix).
 * In Docker: http://commerce:8000 (internal service name).
 * On host dev: http://localhost:8000 (default).
 *
 * MSW does NOT intercept server-side fetches — this always hits the real API.
 */
import { ItemAvailability } from '@/lib/domain-states'
import type { ProductCardItem } from '@/components/product'

const SERVER_BASE =
  (process.env.COMMERCE_API_URL ?? 'http://localhost:8000') + '/api/v1'

// ---------------------------------------------------------------------------
// API response shapes (mirrors Commerce API schemas.py)
// ---------------------------------------------------------------------------

interface ApiCategory {
  id:    number
  name:  string
  karat: string | null
}

interface ApiCatalogItem {
  id:              number
  item_code:       string
  slug:            string
  name:            string
  karat:           string | null
  weight:          number | null
  net_gold_weight: number | null
  has_stones:      boolean
  stock:           number
  price:           number | null
  category:        ApiCategory | null
}

interface ApiCatalogPage {
  items:     ApiCatalogItem[]
  total:     number
  page:      number
  page_size: number
}

interface ApiPricingSnapshot {
  karat_rate_per_gram:     string
  gold_rate_per_gram_24k:  string
  issued_at:               string
  rate_timestamp:          string
  quote_valid_until:       string
  status:                  string
  gold_price_id:           number
  quote_id:                string | null
  pricing_engine_version:  string
}

export interface ApiProductDetail extends ApiCatalogItem {
  barcode:         string | null
  stones_weight:   number | null
  stones_value:    number | null
  count:           number | null
  wage:            number | null
  description:     string | null
  pricing_snapshot: ApiPricingSnapshot | null
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

async function serverFetch<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${SERVER_BASE}${path}`, {
      next: { revalidate: 30 },   // ISR: revalidate every 30 s
    })
    if (!res.ok) return null
    return res.json() as Promise<T>
  } catch {
    return null
  }
}

// ---------------------------------------------------------------------------
// Public fetch API
// ---------------------------------------------------------------------------

export interface FetchProductsParams {
  karat?:      string
  category_id?: number
  in_stock?:   boolean
  page?:       number
  page_size?:  number
}

export async function fetchProducts(
  params: FetchProductsParams = {},
): Promise<ApiCatalogItem[]> {
  const qs = new URLSearchParams()
  if (params.karat)       qs.set('karat',       params.karat)
  if (params.category_id) qs.set('category_id', String(params.category_id))
  if (params.in_stock != null) qs.set('in_stock', String(params.in_stock))
  if (params.page)        qs.set('page',        String(params.page))
  if (params.page_size)   qs.set('page_size',   String(params.page_size))

  const query = qs.toString() ? `?${qs}` : ''
  const data = await serverFetch<ApiCatalogPage>(`/catalog/products${query}`)
  return data?.items ?? []
}

export async function fetchProductDetail(slug: string): Promise<ApiProductDetail | null> {
  return serverFetch<ApiProductDetail>(`/catalog/products/${slug}`)
}

// ---------------------------------------------------------------------------
// Adapter: ApiCatalogItem → ProductCardItem
// ---------------------------------------------------------------------------

const VALID_KARATS = new Set([18, 21, 22, 24])

function parseKarat(raw: string | null): 18 | 21 | 22 | 24 {
  const n = raw ? parseInt(raw, 10) : NaN
  return (VALID_KARATS.has(n) ? n : 21) as 18 | 21 | 22 | 24
}

export function toCatalogCardItem(item: ApiCatalogItem): ProductCardItem {
  return {
    id:           item.slug,     // slug drives /p/[slug] URL routing
    name:         item.name,
    karat:        parseKarat(item.karat),
    weight:       item.weight ?? 0,
    price:        item.price ?? 0,
    availability: item.stock > 0 ? ItemAvailability.AVAILABLE : ItemAvailability.SOLD,
    // img is optional — ProductImage shows a placeholder when absent
  }
}

// ---------------------------------------------------------------------------
// Adapter: ApiProductDetail → price breakdown rows
// ---------------------------------------------------------------------------

const TAX_RATE = 0.15

export function toBreakdownRows(
  detail: ApiProductDetail,
): Array<{ label: string; value: string }> {
  const snap = detail.pricing_snapshot
  const fmt  = (n: number) =>
    n.toLocaleString('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

  if (snap) {
    const rate     = parseFloat(snap.karat_rate_per_gram)
    const netGold  = detail.net_gold_weight ?? detail.weight ?? 0
    const goldComp = netGold * rate
    const wage     = detail.wage ?? 0
    const stones   = detail.stones_value ?? 0
    const subtotal = goldComp + wage + stones
    const tax      = subtotal * TAX_RATE

    const rows: Array<{ label: string; value: string }> = [
      { label: `مكوّن الذهب (${netGold}غ × ${rate.toFixed(2)})`, value: fmt(goldComp) },
    ]
    if (wage > 0)   rows.push({ label: 'المصنعية',      value: fmt(wage) })
    if (stones > 0) rows.push({ label: 'الأحجار',       value: fmt(stones) })
    rows.push(       { label: `الضريبة (${TAX_RATE * 100}%)`, value: fmt(tax) })
    return rows
  }

  // Fallback: price-only row when gold rate is HALTED or missing
  if (detail.price) {
    const preVat = detail.price / (1 + TAX_RATE)
    const tax    = detail.price - preVat
    return [
      { label: 'سعر القطعة (قبل الضريبة)', value: fmt(preVat) },
      { label: `الضريبة (${TAX_RATE * 100}%)`,   value: fmt(tax)    },
    ]
  }

  return []
}
