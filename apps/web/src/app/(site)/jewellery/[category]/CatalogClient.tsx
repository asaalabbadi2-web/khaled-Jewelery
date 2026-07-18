'use client'

import { useState, useMemo, useCallback } from 'react'
import { X, SlidersHorizontal } from 'lucide-react'
import { ProductCard } from '@/components/product'
import { COPY } from '@/lib/contract-copy'
import type { MockCatalogItem } from '@/mocks/catalog-data'

interface Props {
  items:       MockCatalogItem[]
  categoryName:string
}

type Karat    = 24 | 21 | 18
type Weight   = 'lt5' | '5to10' | 'gt10'
type PriceRng = 'lt1k' | '1to2k' | 'gt2k'
type SortKey  = 'newest' | 'priceAsc' | 'priceDesc' | 'weight'

const SORT_OPTIONS: { key: SortKey; label: string }[] = [
  { key: 'newest',    label: COPY.catalog.sortNewest    },
  { key: 'priceAsc',  label: COPY.catalog.sortPriceAsc  },
  { key: 'priceDesc', label: COPY.catalog.sortPriceDesc },
  { key: 'weight',    label: COPY.catalog.sortWeight    },
]

const KARAT_OPTIONS: { key: Karat; label: string }[] = [
  { key: 24, label: COPY.catalog.karat24 },
  { key: 21, label: COPY.catalog.karat21 },
  { key: 18, label: COPY.catalog.karat18 },
]

const WEIGHT_OPTIONS: { key: Weight; label: string }[] = [
  { key: 'lt5',    label: COPY.catalog.weightLt5    },
  { key: '5to10',  label: COPY.catalog.weight5to10  },
  { key: 'gt10',   label: COPY.catalog.weightGt10   },
]

const PRICE_OPTIONS: { key: PriceRng; label: string }[] = [
  { key: 'lt1k',   label: COPY.catalog.priceRangeLt1000  },
  { key: '1to2k',  label: COPY.catalog.priceRange1to2k   },
  { key: 'gt2k',   label: COPY.catalog.priceRangeGt2k    },
]

const PAGE_SIZE = 6

function matchesWeight(item: MockCatalogItem, sel: Weight[]): boolean {
  if (sel.length === 0) return true
  return sel.some(w =>
    w === 'lt5'    ? item.weight < 5  :
    w === '5to10'  ? item.weight >= 5 && item.weight <= 10 :
                     item.weight > 10
  )
}

function matchesPrice(item: MockCatalogItem, sel: PriceRng[]): boolean {
  if (sel.length === 0) return true
  return sel.some(p =>
    p === 'lt1k'  ? item.price < 1_000 :
    p === '1to2k' ? item.price >= 1_000 && item.price <= 2_000 :
                    item.price > 2_000
  )
}

function applySorting(items: MockCatalogItem[], sort: SortKey): MockCatalogItem[] {
  const copy = [...items]
  if (sort === 'priceAsc')  return copy.sort((a, b) => a.price - b.price)
  if (sort === 'priceDesc') return copy.sort((a, b) => b.price - a.price)
  if (sort === 'weight')    return copy.sort((a, b) => a.weight - b.weight)
  return copy
}

function toggle<T>(arr: T[], val: T): T[] {
  return arr.includes(val) ? arr.filter(x => x !== val) : [...arr, val]
}

export function CatalogClient({ items, categoryName }: Props) {
  const [sort,       setSort]       = useState<SortKey>('newest')
  const [karats,     setKarats]     = useState<Karat[]>([])
  const [weights,    setWeights]    = useState<Weight[]>([])
  const [prices,     setPrices]     = useState<PriceRng[]>([])
  const [page,       setPage]       = useState(1)
  const [sheetOpen,  setSheetOpen]  = useState(false)

  const filtered = useMemo(() => {
    let list = items.filter(item =>
      (karats.length === 0 || karats.includes(item.karat)) &&
      matchesWeight(item, weights) &&
      matchesPrice(item, prices)
    )
    return applySorting(list, sort)
  }, [items, karats, weights, prices, sort])

  const totalPages  = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const safePage    = Math.min(page, totalPages)
  const pageItems   = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE)
  const activeCount = karats.length + weights.length + prices.length

  const resetFilters = useCallback(() => {
    setKarats([])
    setWeights([])
    setPrices([])
    setPage(1)
  }, [])

  const filterPanel = (
    <div className="flex flex-col gap-6">
      {/* Karat */}
      <div>
        <p className="text-xs font-medium text-charcoal mb-2">{COPY.catalog.karatGroup}</p>
        <div className="flex flex-wrap gap-2">
          {KARAT_OPTIONS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => { setKarats(prev => toggle(prev, key)); setPage(1) }}
              className={`px-3 py-1 rounded-sm text-xs border transition-colors ${
                karats.includes(key)
                  ? 'bg-gold/10 border-gold/50 text-charcoal'
                  : 'border-muted/30 text-muted hover:border-gold/30'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Weight */}
      <div>
        <p className="text-xs font-medium text-charcoal mb-2">{COPY.catalog.weightGroup}</p>
        <div className="flex flex-col gap-1.5">
          {WEIGHT_OPTIONS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => { setWeights(prev => toggle(prev, key)); setPage(1) }}
              className={`text-right px-3 py-1.5 rounded-sm text-xs border transition-colors ${
                weights.includes(key)
                  ? 'bg-gold/10 border-gold/50 text-charcoal'
                  : 'border-muted/30 text-muted hover:border-gold/30'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Price */}
      <div>
        <p className="text-xs font-medium text-charcoal mb-2">{COPY.catalog.priceGroup}</p>
        <div className="flex flex-col gap-1.5">
          {PRICE_OPTIONS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => { setPrices(prev => toggle(prev, key)); setPage(1) }}
              className={`text-right px-3 py-1.5 rounded-sm text-xs border transition-colors ${
                prices.includes(key)
                  ? 'bg-gold/10 border-gold/50 text-charcoal'
                  : 'border-muted/30 text-muted hover:border-gold/30'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Clear */}
      {activeCount > 0 && (
        <button
          onClick={resetFilters}
          className="text-xs text-muted hover:text-charcoal underline text-right"
        >
          {COPY.catalog.filterClear}
        </button>
      )}
    </div>
  )

  // Build removable chip list for active filters
  const activeChips: Array<{ label: string; onRemove: () => void }> = [
    ...karats.map(k => ({
      label:    KARAT_OPTIONS.find(o => o.key === k)!.label,
      onRemove: () => { setKarats(prev => prev.filter(x => x !== k)); setPage(1) },
    })),
    ...weights.map(w => ({
      label:    WEIGHT_OPTIONS.find(o => o.key === w)!.label,
      onRemove: () => { setWeights(prev => prev.filter(x => x !== w)); setPage(1) },
    })),
    ...prices.map(p => ({
      label:    PRICE_OPTIONS.find(o => o.key === p)!.label,
      onRemove: () => { setPrices(prev => prev.filter(x => x !== p)); setPage(1) },
    })),
  ]

  // Page numbers for numbered pagination (show all when ≤7 pages)
  const pageNumbers = Array.from({ length: totalPages }, (_, i) => i + 1)

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 pb-16">
      {/* Title + count + controls row */}
      <div className="flex items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="text-xl font-semibold text-charcoal tracking-[-0.02em]">
            {categoryName}
          </h1>
          <p className="text-muted text-xs mt-0.5">
            {COPY.catalog.resultsCount(filtered.length)}
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Sort dropdown */}
          <div className="flex items-center gap-1.5">
            <label htmlFor="sort-select" className="text-xs text-muted hidden sm:block">
              {COPY.catalog.sortLabel}
            </label>
            <select
              id="sort-select"
              value={sort}
              onChange={e => { setSort(e.target.value as SortKey); setPage(1) }}
              className="border border-muted/30 rounded-sm bg-surface text-charcoal text-xs px-2 py-1.5 focus:outline-none focus:border-gold/50"
            >
              {SORT_OPTIONS.map(o => (
                <option key={o.key} value={o.key}>{o.label}</option>
              ))}
            </select>
          </div>

          {/* Mobile filter button */}
          <button
            onClick={() => setSheetOpen(true)}
            className="lg:hidden flex items-center gap-1.5 border border-muted/30 rounded-sm px-3 py-1.5 text-xs text-muted hover:border-gold/30 transition-colors"
            aria-label={COPY.catalog.filterAria(activeCount)}
          >
            <SlidersHorizontal size={13} aria-hidden="true" />
            {COPY.catalog.filterCta(activeCount)}
          </button>
        </div>
      </div>

      {/* Active filter chips — removable tags */}
      {activeChips.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-5" aria-label="الفلاتر النشطة">
          {activeChips.map(chip => (
            <button
              key={chip.label}
              onClick={chip.onRemove}
              className="flex items-center gap-1 bg-gold/10 border border-gold/30 text-charcoal text-xs px-2.5 py-1 rounded-sm hover:bg-gold/20 transition-colors"
              aria-label={`إزالة فلتر: ${chip.label}`}
            >
              {chip.label}
              <X size={10} aria-hidden="true" className="text-muted mt-px" />
            </button>
          ))}
        </div>
      )}

      <div className="flex gap-8">
        {/* Desktop sidebar */}
        <aside className="hidden lg:block w-44 shrink-0">
          <p className="text-xs font-semibold text-charcoal mb-4">{COPY.catalog.filterLabel}</p>
          {filterPanel}
        </aside>

        {/* Results */}
        <div className="flex-1 min-w-0">
          {pageItems.length === 0 ? (
            /* Empty state */
            <div className="text-center py-16">
              <p className="text-charcoal font-medium mb-2">
                {filtered.length === 0 && activeCount > 0 ? COPY.catalog.emptyFiltered : COPY.catalog.trulyEmpty}
              </p>
              <p className="text-muted text-sm mb-4">
                {filtered.length === 0 && activeCount > 0 ? COPY.catalog.emptyFilteredSub : COPY.catalog.trulyEmptySub}
              </p>
              {activeCount > 0 && (
                <button
                  onClick={resetFilters}
                  className="text-xs border border-gold/30 text-muted px-4 py-2 rounded-sm hover:border-gold/50 transition-colors"
                >
                  {COPY.catalog.clearFiltersCta}
                </button>
              )}
            </div>
          ) : (
            <div
              className="grid grid-cols-2 sm:grid-cols-3 gap-4 sm:gap-5"
              role="list"
              aria-label={COPY.catalog.resultsAria}
            >
              {pageItems.map(p => (
                <div key={p.id} role="listitem">
                  <ProductCard product={p} />
                </div>
              ))}
            </div>
          )}

          {/* Numbered pagination */}
          {totalPages > 1 && (
            <nav
              className="flex items-center justify-center gap-1.5 mt-10"
              aria-label={COPY.catalog.paginationAria}
            >
              <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={safePage <= 1}
                className="text-xs border border-muted/30 rounded-sm px-3 py-1.5 text-muted disabled:opacity-30 hover:border-gold/30 transition-colors"
              >
                {COPY.catalog.paginationPrev}
              </button>
              {pageNumbers.map(n => (
                <button
                  key={n}
                  onClick={() => setPage(n)}
                  aria-current={n === safePage ? 'page' : undefined}
                  className={[
                    'w-8 h-8 rounded-sm text-xs tabular-nums transition-colors',
                    n === safePage
                      ? 'bg-charcoal text-ivory border border-charcoal'
                      : 'border border-muted/30 text-muted hover:border-gold/30',
                  ].join(' ')}
                >
                  {n}
                </button>
              ))}
              <button
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={safePage >= totalPages}
                className="text-xs border border-muted/30 rounded-sm px-3 py-1.5 text-muted disabled:opacity-30 hover:border-gold/30 transition-colors"
              >
                {COPY.catalog.paginationNext}
              </button>
            </nav>
          )}
        </div>
      </div>

      {/* Mobile filter bottom-sheet */}
      {sheetOpen && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-40 bg-charcoal/40"
            aria-hidden="true"
            onClick={() => setSheetOpen(false)}
          />
          {/* Sheet */}
          <div
            role="dialog"
            aria-label={COPY.catalog.filterLabel}
            className="fixed bottom-0 inset-x-0 z-50 bg-surface rounded-t-lg max-h-[80vh] overflow-y-auto p-5"
          >
            <div className="flex items-center justify-between mb-5">
              <p className="text-sm font-semibold text-charcoal">{COPY.catalog.filterLabel}</p>
              <button
                onClick={() => setSheetOpen(false)}
                aria-label={COPY.catalog.filterClose}
                className="text-muted hover:text-charcoal transition-colors"
              >
                <X size={18} aria-hidden="true" />
              </button>
            </div>
            {filterPanel}
            <button
              onClick={() => setSheetOpen(false)}
              className="w-full mt-6 bg-bronze text-surface py-3 rounded-sm text-sm font-semibold hover:bg-bronze-hover transition-colors"
            >
              {COPY.catalog.filterApply}
            </button>
          </div>
        </>
      )}
    </div>
  )
}
