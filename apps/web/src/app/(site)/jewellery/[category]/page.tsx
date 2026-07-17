import { CatalogClient } from './CatalogClient'
import { COPY } from '@/lib/contract-copy'
import { MOCK_CATALOG } from '@/mocks/catalog-data'

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
  const name = CATEGORY_NAMES[category] ?? COPY.nav.jewellery

  return (
    <main>
      <CatalogClient items={MOCK_CATALOG} categoryName={name} />
    </main>
  )
}

export function generateStaticParams() {
  return [{ category: 'rings' }, { category: 'bracelets' }, { category: 'necklaces' }, { category: 'sets' }]
}
