'use client'

import {
  createContext,
  useContext,
  useState,
  useCallback,
  type ReactNode,
} from 'react'

interface SearchCtxValue {
  open:        boolean
  openSearch:  () => void
  closeSearch: () => void
}

const SearchCtx = createContext<SearchCtxValue>({
  open:        false,
  openSearch:  () => {},
  closeSearch: () => {},
})

export const useSearch = () => useContext(SearchCtx)

export function SearchProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const openSearch  = useCallback(() => setOpen(true),  [])
  const closeSearch = useCallback(() => setOpen(false), [])
  return (
    <SearchCtx.Provider value={{ open, openSearch, closeSearch }}>
      {children}
    </SearchCtx.Provider>
  )
}
