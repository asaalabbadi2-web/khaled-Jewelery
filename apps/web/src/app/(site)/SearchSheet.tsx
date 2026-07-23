'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { X, Search } from 'lucide-react'
import { useSearch } from '@/lib/search-context'
import { catalogApi, type CatalogItem } from '@/lib/api'
import { COPY } from '@/lib/contract-copy'
import { pr } from '@/lib/format'
import { ImageWithFallback } from '@/components/ui/ImageWithFallback'

export function SearchSheet() {
  const { open, closeSearch } = useSearch()
  const router    = useRouter()
  const inputRef  = useRef<HTMLInputElement>(null)
  const [query,   setQuery]   = useState('')
  const [results, setResults] = useState<CatalogItem[]>([])
  const [loading, setLoading] = useState(false)

  // Focus / reset on open-state change
  useEffect(() => {
    if (open) {
      inputRef.current?.focus()
    } else {
      setQuery('')
      setResults([])
      setLoading(false)
    }
  }, [open])

  // Debounced search (300 ms)
  useEffect(() => {
    if (!open || !query.trim()) {
      setResults([])
      setLoading(false)
      return
    }
    setLoading(true)
    const id = setTimeout(() => {
      catalogApi
        .search(query.trim())
        .then(data => setResults(data.items.slice(0, 6)))
        .catch(() => setResults([]))
        .finally(() => setLoading(false))
    }, 300)
    return () => clearTimeout(id)
  }, [query, open])

  // Escape key
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') closeSearch() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, closeSearch])

  if (!open) return null

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={COPY.search.overlayLabel}
      className="fixed inset-0 z-50 flex flex-col items-center pt-20 px-4"
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-charcoal/60 backdrop-blur-sm"
        onClick={closeSearch}
        aria-hidden="true"
      />

      {/* Panel */}
      <div className="relative w-full max-w-xl bg-surface rounded-2xl shadow-2xl overflow-hidden">

        {/* Input row */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-muted/10" dir="rtl">
          <Search size={16} className="text-muted shrink-0" aria-hidden="true" />
          <input
            ref={inputRef}
            type="search"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder={COPY.search.inputPlaceholder}
            aria-label={COPY.search.overlayLabel}
            className="flex-1 bg-transparent text-charcoal text-sm outline-none placeholder:text-muted/60"
          />
          <button
            onClick={closeSearch}
            aria-label={COPY.search.closeLabel}
            className="text-muted hover:text-charcoal p-1 shrink-0 transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        {/* Results list */}
        {query.trim() && (
          <ul
            role="listbox"
            aria-label={COPY.search.resultsLabel}
            className="max-h-80 overflow-y-auto"
          >
            {loading && (
              <li className="flex justify-center items-center py-8">
                <span
                  className="inline-block w-5 h-5 border-2 border-muted/30 border-t-gold rounded-full animate-spin"
                  aria-label="جارٍ البحث"
                />
              </li>
            )}

            {!loading && results.length === 0 && (
              <li className="py-8 text-center text-muted text-sm">
                {COPY.search.noResults}
              </li>
            )}

            {!loading && results.map(item => (
              <li key={item.id} role="option" aria-selected="false">
                <button
                  dir="rtl"
                  className="w-full flex items-center gap-3 px-4 py-3 hover:bg-muted/5 text-right transition-colors"
                  onClick={() => { closeSearch(); router.push(`/p/${item.slug}`) }}
                >
                  <div className="w-12 h-12 rounded-lg overflow-hidden bg-image-bg shrink-0">
                    <ImageWithFallback
                      src={item.img}
                      alt={item.name}
                      className="w-full h-full object-cover"
                    />
                  </div>

                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-charcoal font-medium truncate">{item.name}</p>
                    <p className="text-xs text-muted mt-0.5">
                      {item.karat}ك · {item.weight}غ
                    </p>
                  </div>

                  <div className="shrink-0 text-left" dir="ltr">
                    <span className="text-sm font-semibold tabular-nums text-charcoal">
                      {pr(item.price)}
                    </span>
                    <span className="text-xs text-muted mr-1">{COPY.search.currencySuffix}</span>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
