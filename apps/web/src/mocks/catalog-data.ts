/**
 * Single source of truth for mock catalog data.
 * Used by MSW handlers (browser) and server-side page lookups.
 * When real Commerce API ships, pages will fetch from API; this file stays for MSW only.
 */
import { ItemAvailability } from '@/lib/domain-states'

export interface MockCatalogItem {
  id:           string
  slug:         string
  name:         string
  karat:        18 | 21 | 24
  weight:       number
  price:        number
  availability: ItemAvailability
  img:          string
}

export const MOCK_CATALOG: MockCatalogItem[] = [
  { id: 'R-21-0342', slug: 'R-21-0342', name: 'خاتم سوليتير',  karat: 21, weight: 8.45,  price: 1_215, availability: ItemAvailability.AVAILABLE, img: 'https://images.unsplash.com/photo-1605100804763-247f67b3557e?w=600&h=600&fit=crop&auto=format' },
  { id: 'R-21-0418', slug: 'R-21-0418', name: 'خاتم تريلوجي',  karat: 21, weight: 9.30,  price: 2_340, availability: ItemAvailability.RESERVED,  img: 'https://images.unsplash.com/photo-1589128777073-263566ae5e4d?w=600&h=600&fit=crop&auto=format' },
  { id: 'R-18-0314', slug: 'R-18-0314', name: 'خاتم هالو',      karat: 18, weight: 5.60,  price: 1_480, availability: ItemAvailability.AVAILABLE, img: 'https://images.unsplash.com/photo-1598560917807-1bae44bd2be8?w=600&h=600&fit=crop&auto=format' },
  { id: 'R-21-0385', slug: 'R-21-0385', name: 'خاتم بافلي',     karat: 21, weight: 7.20,  price: 1_651, availability: ItemAvailability.AVAILABLE, img: 'https://images.unsplash.com/photo-1611955167811-4711904bb9f8?w=600&h=600&fit=crop&auto=format' },
  { id: 'R-21-0466', slug: 'R-21-0466', name: 'خاتم فينيتاج',   karat: 21, weight: 11.80, price: 3_050, availability: ItemAvailability.AVAILABLE, img: 'https://images.unsplash.com/photo-1602173574767-37ac01994b2a?w=600&h=600&fit=crop&auto=format' },
  { id: 'R-21-0399', slug: 'R-21-0399', name: 'خاتم كلاسيك',    karat: 21, weight: 7.80,  price: 1_790, availability: ItemAvailability.AVAILABLE, img: 'https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=600&h=600&fit=crop&auto=format' },
  { id: 'B-21-0101', slug: 'B-21-0101', name: 'سوار ترولوجي',   karat: 21, weight: 6.10,  price: 1_400, availability: ItemAvailability.AVAILABLE, img: 'https://images.unsplash.com/photo-1573408301185-9519f94816b5?w=600&h=600&fit=crop&auto=format' },
  { id: 'N-21-0202', slug: 'N-21-0202', name: 'عقد سوليتير',    karat: 21, weight: 4.30,  price:   990, availability: ItemAvailability.AVAILABLE, img: 'https://images.unsplash.com/photo-1515562141207-7a88fb7ce338?w=600&h=600&fit=crop&auto=format' },
]

// Per-item price breakdown (label + SAR value)
export const MOCK_BREAKDOWNS: Record<string, Array<{ label: string; value: string }>> = {
  'R-21-0342': [
    { label: 'مكوّن الذهب (8.450غ × 289.40)', value: '2,445.43' },
    { label: 'المصنعية',                        value:   '350.00' },
    { label: 'الأحجار',                         value:   '220.00' },
    { label: 'الضريبة (15%)',                   value:   '452.31' },
  ],
}

const defaultBreakdown = (item: MockCatalogItem): Array<{ label: string; value: string }> => [
  { label: `مكوّن الذهب (${item.weight}غ × 289.40)`,
    value: (item.weight * 289.40).toLocaleString('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) },
  { label: 'المصنعية',       value: '250.00' },
  { label: 'الضريبة (15%)', value: (item.price * 0.15).toLocaleString('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) },
]

export function getBreakdown(id: string, item: MockCatalogItem) {
  return MOCK_BREAKDOWNS[id] ?? defaultBreakdown(item)
}

export const MOCK_THUMBNAILS: Record<string, string[]> = {
  'R-21-0342': [
    'https://images.unsplash.com/photo-1589128777073-263566ae5e4d?w=600&h=750&fit=crop&auto=format',
    'https://images.unsplash.com/photo-1598560917807-1bae44bd2be8?w=600&h=750&fit=crop&auto=format',
  ],
}
