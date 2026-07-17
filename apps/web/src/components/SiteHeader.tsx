import { Menu, Search } from 'lucide-react'
import { BRAND_NAME } from '@/lib/brand'
import { COPY } from '@/lib/contract-copy'

type ActivePage = 'catalog' | 'about' | 'track'

export interface SiteHeaderProps {
  onHome?(): void
  onCatalog?(): void
  onAbout?(): void
  onTrack?(): void
  active?: ActivePage
  /** true when GoldLiveBar is visible; shifts header down from top-10 to top-20 */
  hasBanner?: boolean
}

function NavItem({
  pageKey,
  label,
  active,
  onClick,
}: {
  pageKey: ActivePage
  label: string
  active?: ActivePage
  onClick?(): void
}) {
  if (active === pageKey) {
    return (
      <span className="text-charcoal text-sm font-medium" aria-current="page">
        {label}
      </span>
    )
  }
  return (
    <button
      onClick={onClick}
      className="text-muted text-sm hover:text-charcoal transition-colors"
    >
      {label}
    </button>
  )
}

export function SiteHeader({
  onHome,
  onCatalog,
  onAbout,
  onTrack,
  active,
  hasBanner = false,
}: SiteHeaderProps) {
  return (
    <header
      className={`fixed ${hasBanner ? 'top-20' : 'top-10'} inset-x-0 h-16 z-40 bg-surface border-b border-gold/[0.18] flex items-center`}
      aria-label="شريط التنقل الرئيسي"
    >
      <div className="max-w-6xl mx-auto w-full px-4 sm:px-6 lg:px-8 flex items-center">
        <button
          onClick={onHome}
          className="text-charcoal text-base font-semibold tracking-[-0.01em] shrink-0"
        >
          {BRAND_NAME}
        </button>

        <nav className="hidden md:flex items-center gap-7 mx-auto" aria-label="قائمة التنقل">
          <NavItem pageKey="catalog" label={COPY.nav.jewellery} active={active} onClick={onCatalog} />
          <NavItem pageKey="about"   label={COPY.nav.about}     active={active} onClick={onAbout} />
          <NavItem pageKey="track"   label={COPY.nav.track}     active={active} onClick={onTrack} />
        </nav>

        <div className="mr-auto md:mr-0 flex items-center gap-3">
          <button className="hidden md:flex text-muted p-1" aria-label={COPY.nav.search}>
            <Search size={17} />
          </button>
          <button className="flex md:hidden text-muted p-1" aria-label={COPY.nav.menu}>
            <Menu size={20} />
          </button>
        </div>
      </div>
    </header>
  )
}
