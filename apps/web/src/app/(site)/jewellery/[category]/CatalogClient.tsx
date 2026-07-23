'use client'

import { useState, useMemo, useCallback } from 'react'
import { X, SlidersHorizontal, ChevronDown } from 'lucide-react'
import { ProductCard } from '@/components/product'
import { COPY } from '@/lib/contract-copy'
import type { MockCatalogItem } from '@/mocks/catalog-data'

interface Props {
  items:        MockCatalogItem[]
  categoryName: string
}

type Karat   = 24 | 21 | 18
type Weight  = 'lt5' | '5to10' | 'gt10'
type SortKey = 'newest' | 'priceAsc' | 'priceDesc' | 'weight'

const PRICE_MIN = 500
const PRICE_MAX = 20_000
const PAGE_SIZE = 6

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
  { key: 'lt5',   label: COPY.catalog.weightLt5   },
  { key: '5to10', label: COPY.catalog.weight5to10 },
  { key: 'gt10',  label: COPY.catalog.weightGt10  },
]

function matchesWeight(item: MockCatalogItem, sel: Weight[]): boolean {
  if (sel.length === 0) return true
  return sel.some(w =>
    w === 'lt5'   ? item.weight < 5 :
    w === '5to10' ? item.weight >= 5 && item.weight <= 10 :
                    item.weight > 10,
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

// Score each item by how many active filter groups it satisfies; return top-3. (FP-5)
function nearestItems(
  allItems: MockCatalogItem[],
  karats: Karat[],
  weights: Weight[],
  [priceMin, priceMax]: [number, number],
): MockCatalogItem[] {
  return allItems
    .map(item => {
      let score = 0
      if (karats.length === 0 || karats.includes(item.karat)) score++
      if (matchesWeight(item, weights)) score++
      if (item.price >= priceMin && item.price <= priceMax) score++
      return { item, score }
    })
    .filter(({ score }) => score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, 3)
    .map(({ item }) => item)
}

// ── Collapsible filter group (FP-6) ──────────────────────────────────────────

function FilterGroup({ label, open, onToggle, children }: {
  label:    string
  open:     boolean
  onToggle: () => void
  children: React.ReactNode
}) {
  return (
    <div className="border-t border-muted/10 first:border-t-0">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="w-full flex items-center justify-between py-3 text-xs font-medium text-charcoal hover:opacity-80 transition-opacity"
      >
        <span>{label}</span>
        <ChevronDown
          size={14}
          aria-hidden="true"
          className={`text-muted transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
        />
      </button>
      {open && <div className="pb-3">{children}</div>}
    </div>
  )
}

// ── Dual-handle price range slider (FP-6) ─────────────────────────────────────

function PriceRangeSlider({ lo, hi, onChange }: {
  lo:       number
  hi:       number
  onChange: (lo: number, hi: number) => void
}) {
  const loFrac  = (lo - PRICE_MIN) / (PRICE_MAX - PRICE_MIN)
  const hiFrac  = (hi - PRICE_MIN) / (PRICE_MAX - PRICE_MIN)
  // Elevate lo z-index when it's near the top so it remains draggable downward
  const loOnTop = lo > PRICE_MIN + (PRICE_MAX - PRICE_MIN) * 0.9

  return (
    <div className="relative h-6 flex items-center mt-2">
      {/* Track */}
      <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-1 rounded-full bg-muted/20">
        <div
          className="absolute h-full rounded-full bg-gold"
          style={{ left: `${loFrac * 100}%`, right: `${(1 - hiFrac) * 100}%` }}
        />
      </div>

      {/* Visual handles (pointer-events-none — interaction via inputs below) */}
      <div
        aria-hidden="true"
        className="absolute top-1/2 -translate-y-1/2 w-4 h-4 rounded-full bg-gold border-2 border-surface shadow-sm pointer-events-none"
        style={{ left: `calc(${loFrac * 100}% - 8px)` }}
      />
      <div
        aria-hidden="true"
        className="absolute top-1/2 -translate-y-1/2 w-4 h-4 rounded-full bg-gold border-2 border-surface shadow-sm pointer-events-none"
        style={{ left: `calc(${hiFrac * 100}% - 8px)` }}
      />

      {/* Transparent range inputs — thumbs only receive pointer events */}
      <input
        type="range"
        min={PRICE_MIN} max={PRICE_MAX} step={100}
        value={lo}
        onChange={e => onChange(Math.min(Number(e.target.value), hi - 500), hi)}
        className={`absolute inset-0 w-full h-full appearance-none bg-transparent opacity-0 cursor-pointer ${loOnTop ? 'z-10' : 'z-0'}`}
        aria-label={`الحد الأدنى للسعر: ${lo.toLocaleString('en')} ريال`}
      />
      <input
        type="range"
        min={PRICE_MIN} max={PRICE_MAX} step={100}
        value={hi}
        onChange={e => onChange(lo, Math.max(Number(e.target.value), lo + 500))}
        className={`absolute inset-0 w-full h-full appearance-none bg-transparent opacity-0 cursor-pointer ${loOnTop ? 'z-0' : 'z-10'}`}
        aria-label={`الحد الأقصى للسعر: ${hi.toLocaleString('en')} ريال`}
      />
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function CatalogClient({ items, categoryName }: Props) {
  const [sort,       setSort]       = useState<SortKey>('newest')
  const [karats,     setKarats]     = useState<Karat[]>([])
  const [weights,    setWeights]    = useState<Weight[]>([])
  const [priceRange, setPriceRange] = useState<[number, number]>([PRICE_MIN, PRICE_MAX])
  const [page,       setPage]       = useState(1)
  const [sheetOpen,  setSheetOpen]  = useState(false)
  const [openGroups, setOpenGroups] = useState({
    karat:    true,
    weight:   true,
    category: false,
    price:    true,
  })

  const toggleGroup = useCallback((key: keyof typeof openGroups) => {
    setOpenGroups(prev => ({ ...prev, [key]: !prev[key] }))
  }, [])

  const isPriceActive = priceRange[0] > PRICE_MIN || priceRange[1] < PRICE_MAX

  const filtered = useMemo(() => {
    const list = items.filter(item =>
      (karats.length === 0 || karats.includes(item.karat)) &&
      matchesWeight(item, weights) &&
      item.price >= priceRange[0] && item.price <= priceRange[1]
    )
    return applySorting(list, sort)
  }, [items, karats, weights, priceRange, sort])

  const totalPages  = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const safePage    = Math.min(page, totalPages)
  const pageItems   = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE)
  const activeCount = karats.length + weights.length + (isPriceActive ? 1 : 0)

  // Scored proximity suggestions — only computed when filtered is empty and filters are on
  const nearest = useMemo(() => {
    if (filtered.length > 0 || activeCount === 0) return []
    return nearestItems(items, karats, weights, priceRange)
  }, [filtered, activeCount, items, karats, weights, priceRange])

  const resetFilters = useCallback(() => {
    setKarats([])
    setWeights([])
    setPriceRange([PRICE_MIN, PRICE_MAX])
    setPage(1)
  }, [])

  const activeChips: Array<{ label: string; onRemove: () => void }> = [
    ...karats.map(k => ({
      label:    KARAT_OPTIONS.find(o => o.key === k)!.label,
      onRemove: () => { setKarats(prev => prev.filter(x => x !== k)); setPage(1) },
    })),
    ...weights.map(w => ({
      label:    WEIGHT_OPTIONS.find(o => o.key === w)!.label,
      onRemove: () => { setWeights(prev => prev.filter(x => x !== w)); setPage(1) },
    })),
    ...(isPriceActive ? [{
      label:    COPY.catalog.priceRangeChip(priceRange[0], priceRange[1]),
      onRemove: () => { setPriceRange([PRICE_MIN, PRICE_MAX]); setPage(1) },
    }] : []),
  ]

  const pageNumbers = Array.from({ length: totalPages }, (_, i) => i + 1)

  // ── Filter panel shared between desktop sidebar and mobile sheet ───────────

  const filterPanel = (
    <div className="flex flex-col">
      {/* العيار — pills */}
      <FilterGroup
        label={COPY.catalog.karatGroup}
        open={openGroups.karat}
        onToggle={() => toggleGroup('karat')}
      >
        <div className="flex flex-wrap gap-2">
          {KARAT_OPTIONS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
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
      </FilterGroup>

      {/* الوزن — checkboxes */}
      <FilterGroup
        label={COPY.catalog.weightGroup}
        open={openGroups.weight}
        onToggle={() => toggleGroup('weight')}
      >
        <div className="flex flex-col gap-2.5">
          {WEIGHT_OPTIONS.map(({ key, label }) => (
            <label key={key} className="flex items-center gap-2 cursor-pointer group">
              <input
                type="checkbox"
                checked={weights.includes(key)}
                onChange={() => { setWeights(prev => toggle(prev, key)); setPage(1) }}
                className="w-3.5 h-3.5 rounded-sm border-muted/40 accent-gold cursor-pointer"
              />
              <span className="text-xs text-muted group-hover:text-charcoal transition-colors">
                {label}
              </span>
            </label>
          ))}
        </div>
      </FilterGroup>

      {/* الفئة — collapsed by default */}
      <FilterGroup
        label={COPY.catalog.categoryGroup}
        open={openGroups.category}
        onToggle={() => toggleGroup('category')}
      >
        <p className="text-xs text-muted leading-relaxed">{COPY.catalog.categoryGroupHint}</p>
      </FilterGroup>

      {/* السعر — dual range slider */}
      <FilterGroup
        label={COPY.catalog.priceGroup}
        open={openGroups.price}
        onToggle={() => toggleGroup('price')}
      >
        <PriceRangeSlider
          lo={priceRange[0]}
          hi={priceRange[1]}
          onChange={(lo, hi) => { setPriceRange([lo, hi]); setPage(1) }}
        />
        <div className="flex items-center justify-between mt-3">
          <span className="text-[11px] text-muted" dir="ltr">{COPY.catalog.priceMinEdge}</span>
          <span className="text-[11px] text-muted" dir="ltr">{COPY.catalog.priceMaxEdge}</span>
        </div>
      </FilterGroup>

      {activeCount > 0 && (
        <button
          type="button"
          onClick={resetFilters}
          className="mt-1 pt-3 border-t border-muted/10 text-xs text-muted hover:text-charcoal underline text-right transition-colors"
        >
          {COPY.catalog.filterClear}
        </button>
      )}
    </div>
  )

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 pb-16">
      {/* Title + count + controls */}
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

          <button
            type="button"
            onClick={() => setSheetOpen(true)}
            className="lg:hidden flex items-center gap-1.5 border border-muted/30 rounded-sm px-3 py-1.5 text-xs text-muted hover:border-gold/30 transition-colors"
            aria-label={COPY.catalog.filterAria(activeCount)}
          >
            <SlidersHorizontal size={13} aria-hidden="true" />
            {COPY.catalog.filterCta(activeCount)}
          </button>
        </div>
      </div>

      {/* Active filter chips */}
      {activeChips.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-5" aria-label="الفلاتر النشطة">
          {activeChips.map(chip => (
            <button
              key={chip.label}
              type="button"
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
          <p className="text-xs font-semibold text-charcoal mb-3">{COPY.catalog.filterLabel}</p>
          {filterPanel}
        </aside>

        {/* Results */}
        <div className="flex-1 min-w-0">
          {pageItems.length === 0 ? (
            <div>
              {activeCount > 0 ? (
                <>
                  {/* Filtered empty — FC-4: no dead end */}
                  <div className="text-center py-12">
                    <p className="text-charcoal font-medium mb-2">{COPY.catalog.emptyFiltered}</p>
                    <p className="text-muted text-sm mb-6">{COPY.catalog.emptyFilteredSub}</p>
                    <button
                      type="button"
                      onClick={resetFilters}
                      className="bg-bronze text-surface px-5 py-2.5 rounded-sm text-sm font-semibold hover:bg-bronze-hover transition-colors"
                    >
                      {COPY.catalog.clearFiltersCta}
                    </button>
                  </div>

                  {/* Nearest suggestions strip */}
                  {nearest.length > 0 && (
                    <div className="mt-8 border-t border-gold/10 pt-8">
                      <p className="text-xs font-semibold text-charcoal mb-4">
                        {COPY.catalog.nearestLabel}
                      </p>
                      <div
                        className="grid grid-cols-2 sm:grid-cols-3 gap-4 sm:gap-5"
                        role="list"
                        aria-label={COPY.catalog.nearestLabel}
                      >
                        {nearest.map(item => (
                          <div key={item.id} role="listitem">
                            <ProductCard product={item} />
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              ) : (
                <div className="text-center py-16">
                  <p className="text-charcoal font-medium mb-2">{COPY.catalog.trulyEmpty}</p>
                  <p className="text-muted text-sm">{COPY.catalog.trulyEmptySub}</p>
                </div>
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
                type="button"
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={safePage <= 1}
                className="text-xs border border-muted/30 rounded-sm px-3 py-1.5 text-muted disabled:opacity-30 hover:border-gold/30 transition-colors"
              >
                {COPY.catalog.paginationPrev}
              </button>
              {pageNumbers.map(n => (
                <button
                  key={n}
                  type="button"
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
                type="button"
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
          <div
            className="fixed inset-0 z-40 bg-charcoal/40"
            aria-hidden="true"
            onClick={() => setSheetOpen(false)}
          />
          <div
            role="dialog"
            aria-label={COPY.catalog.filterLabel}
            className="fixed bottom-0 inset-x-0 z-50 bg-surface rounded-t-lg max-h-[80vh] overflow-y-auto p-5"
          >
            <div className="flex items-center justify-between mb-5">
              <p className="text-sm font-semibold text-charcoal">{COPY.catalog.filterLabel}</p>
              <button
                type="button"
                onClick={() => setSheetOpen(false)}
                aria-label={COPY.catalog.filterClose}
                className="text-muted hover:text-charcoal transition-colors"
              >
                <X size={18} aria-hidden="true" />
              </button>
            </div>
            {filterPanel}
            <button
              type="button"
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
