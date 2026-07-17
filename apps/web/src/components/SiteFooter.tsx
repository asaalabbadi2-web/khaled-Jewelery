import { COPY } from '@/lib/contract-copy'

export interface SiteFooterProps {
  onSelect?(name: string): void
  onCatalog?(): void
  onTrack?(): void
}

type FooterLink = {
  label: string
  onClick?: () => void
}

export function SiteFooter({ onSelect, onCatalog, onTrack }: SiteFooterProps) {
  const links: FooterLink[] = [
    { label: COPY.nav.jewellery, onClick: onCatalog },
    { label: COPY.nav.about,     onClick: () => onSelect?.(COPY.nav.about) },
    { label: COPY.nav.track,     onClick: onTrack },
    { label: COPY.footer.links.faq,     onClick: () => onSelect?.(COPY.footer.links.faq) },
    { label: COPY.footer.links.returns, onClick: () => onSelect?.(COPY.footer.links.returns) },
    { label: COPY.footer.links.terms,   onClick: () => onSelect?.(COPY.footer.links.terms) },
    { label: COPY.footer.links.privacy, onClick: () => onSelect?.(COPY.footer.links.privacy) },
  ]

  return (
    <footer className="border-t border-gold/15 bg-surface mt-16">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-9">
        <nav className="flex flex-wrap gap-x-6 gap-y-2" aria-label={COPY.footer.navAriaLabel}>
          {links.map(({ label, onClick }) => (
            <button
              key={label}
              onClick={onClick}
              className="text-muted text-xs hover:text-charcoal transition-colors"
            >
              {label}
            </button>
          ))}
        </nav>
        <p className="mt-6 pt-6 border-t border-gold/15 text-muted text-xs">
          {COPY.footer.priceNote}
        </p>
      </div>
    </footer>
  )
}
