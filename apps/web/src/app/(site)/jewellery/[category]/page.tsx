import { CatalogClient } from './CatalogClient'
import { COPY } from '@/lib/contract-copy'
import { fetchProducts, toCatalogCardItem } from '@/lib/api/server'

// Maps URL segment → Commerce API category_id (must match seed/commerce_seed.sql)
const CATEGORY_IDS: Record<string, number> = {
  rings:     1,
  bracelets: 2,
  necklaces: 3,
}

const CATEGORY_NAMES: Record<string, string> = {
  rings:     COPY.home.colRings,
  bracelets: COPY.home.colBracelets,
  necklaces: COPY.home.colNecklaces,
  sets:      COPY.home.colSets,
}

export default async function CatalogPage({
  params,
}: {
  params: Promise<{ category: string }>
}) {
  const { category } = await params
  const name        = CATEGORY_NAMES[category] ?? COPY.nav.jewellery
  const category_id = CATEGORY_IDS[category]

  const apiItems = await fetchProducts(category_id ? { category_id } : {})
  const items    = apiItems.map(toCatalogCardItem)

  return (
    <main>
      <CatalogClient items={items} categoryName={name} />
    </main>
  )
}

export function generateStaticParams() {
  return [{ category: 'rings' }, { category: 'bracelets' }, { category: 'necklaces' }, { category: 'sets' }]
}
