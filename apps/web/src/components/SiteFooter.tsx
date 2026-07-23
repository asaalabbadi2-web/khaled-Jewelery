import Link from 'next/link'
import { COPY } from '@/lib/contract-copy'

type FooterLink = {
  label: string
  href: string
}

const links: FooterLink[] = [
  { label: COPY.nav.jewellery,        href: '/jewellery/rings' },
  { label: COPY.nav.about,            href: '/about'           },
  { label: COPY.nav.track,            href: '/track'           },
  { label: COPY.footer.links.faq,     href: '/faq'             },
  { label: COPY.footer.links.returns, href: '/returns'         },
  { label: COPY.footer.links.terms,   href: '/terms'           },
  { label: COPY.footer.links.privacy, href: '/privacy'         },
]

export function SiteFooter() {
  return (
    <footer className="border-t border-gold/15 bg-surface mt-16">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-9">
        <nav className="flex flex-wrap gap-x-6 gap-y-2" aria-label={COPY.footer.navAriaLabel}>
          {links.map(({ label, href }) => (
            <Link
              key={label}
              href={href}
              className="text-muted text-xs hover:text-charcoal transition-colors"
            >
              {label}
            </Link>
          ))}
        </nav>
        <p className="mt-6 pt-6 border-t border-gold/15 text-muted text-xs">
          {COPY.footer.priceNote}
        </p>
      </div>
    </footer>
  )
}
