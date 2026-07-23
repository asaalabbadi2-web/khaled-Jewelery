import { notFound } from 'next/navigation'
import { ChevronDown } from 'lucide-react'
import { COPY } from '@/lib/contract-copy'

// ── Per-page renderer helpers ────────────────────────────────────────────────

function SectionedPage({ title, sections }: {
  title:    string
  sections: ReadonlyArray<{ readonly heading: string; readonly body: string }>
}) {
  return (
    <article className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 pb-16">
      <h1 className="text-2xl font-semibold text-charcoal tracking-[-0.02em] mb-8 border-b border-gold/15 pb-5">
        {title}
      </h1>
      <div className="flex flex-col gap-8">
        {sections.map(({ heading, body }) => (
          <section key={heading}>
            <h2 className="text-sm font-semibold text-charcoal mb-2">{heading}</h2>
            <p className="text-muted text-sm leading-relaxed">{body}</p>
          </section>
        ))}
      </div>
    </article>
  )
}

function FaqPage() {
  return (
    <article className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 pb-16">
      <h1 className="text-2xl font-semibold text-charcoal tracking-[-0.02em] mb-8 border-b border-gold/15 pb-5">
        {COPY.staticPages.faq.title}
      </h1>
      <div className="flex flex-col divide-y divide-gold/10">
        {COPY.staticPages.faq.items.map((item, i) => (
          <details key={i} className="group">
            <summary className="flex items-center justify-between gap-4 py-4 cursor-pointer list-none">
              <span className="text-sm font-medium text-charcoal leading-snug">
                {item.q}
              </span>
              <ChevronDown
                size={16}
                aria-hidden="true"
                className="text-gold shrink-0 transition-transform duration-200 group-open:rotate-180"
              />
            </summary>
            <p className="text-muted text-sm leading-relaxed pb-4 pr-1">
              {item.a}
            </p>
          </details>
        ))}
      </div>
    </article>
  )
}

function AboutPage() {
  const { about } = COPY.staticPages

  return (
    <article className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 pb-16">
      <h1 className="text-2xl font-semibold text-charcoal tracking-[-0.02em] mb-8 border-b border-gold/15 pb-5">
        {about.title}
      </h1>
      <p className="text-muted text-sm leading-relaxed mb-8">{about.intro}</p>

      <section className="mb-8">
        <h2 className="text-sm font-semibold text-charcoal mb-2">{about.missionLabel}</h2>
        <p className="text-muted text-sm leading-relaxed">{about.mission}</p>
      </section>

      <section>
        <h2 className="text-sm font-semibold text-charcoal mb-4">{about.branchesLabel}</h2>
        <div className="flex flex-col gap-3">
          {about.branches.map(branch => (
            <div
              key={branch.name}
              className="border border-gold/20 rounded-sm p-4 bg-surface"
            >
              <p className="text-charcoal text-sm font-medium">{branch.name}</p>
              <p className="text-muted text-xs mt-0.5">{branch.address}</p>
            </div>
          ))}
        </div>
      </section>
    </article>
  )
}

function TermsPage() {
  const { terms } = COPY.staticPages
  return (
    <article className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 pb-16">
      <div className="mb-8 border-b border-gold/15 pb-5">
        <h1 className="text-2xl font-semibold text-charcoal tracking-[-0.02em]">
          {terms.title}
        </h1>
        <p className="text-muted text-xs mt-2">
          {terms.lastUpdatedLabel} {terms.lastUpdated}
        </p>
      </div>

      {/* Table of contents */}
      <nav aria-label={terms.tocLabel} className="mb-8 border border-gold/15 rounded-sm p-4 bg-surface">
        <p className="text-xs font-semibold text-charcoal mb-2">{terms.tocLabel}</p>
        <ol className="flex flex-col gap-1 list-decimal list-inside marker:text-muted marker:text-xs">
          {terms.sections.map((s, i) => (
            <li key={i}>
              <a href={`#terms-${i}`} className="text-xs text-muted hover:text-charcoal underline underline-offset-2">
                {s.heading}
              </a>
            </li>
          ))}
        </ol>
      </nav>

      <div className="flex flex-col gap-8">
        {terms.sections.map((s, i) => {
          const isPriceLock = i === terms.priceLockIndex
          return (
            <section key={i} id={`terms-${i}`}>
              {isPriceLock ? (
                <div className="border border-gold/30 rounded-sm p-4 bg-gold/5">
                  <h2 className="text-sm font-semibold text-charcoal mb-2">{s.heading}</h2>
                  <p className="text-muted text-sm leading-relaxed">{s.body}</p>
                </div>
              ) : (
                <>
                  <h2 className="text-sm font-semibold text-charcoal mb-2">{s.heading}</h2>
                  <p className="text-muted text-sm leading-relaxed">{s.body}</p>
                </>
              )}
            </section>
          )
        })}
      </div>
    </article>
  )
}

// ── Route ────────────────────────────────────────────────────────────────────

export default async function StaticPage({ params }: { params: Promise<{ policy: string }> }) {
  const { policy } = await params

  if (policy === 'faq')   return <FaqPage />
  if (policy === 'about') return <AboutPage />

  if (policy === 'terms')
    return <TermsPage />
  if (policy === 'returns')
    return <SectionedPage title={COPY.staticPages.returns.title} sections={COPY.staticPages.returns.sections} />
  if (policy === 'privacy')
    return <SectionedPage title={COPY.staticPages.privacy.title} sections={COPY.staticPages.privacy.sections} />

  notFound()
}

export function generateStaticParams() {
  return ['about', 'faq', 'returns', 'terms', 'privacy'].map(policy => ({ policy }))
}
