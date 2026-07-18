'use client'

import { notFound } from 'next/navigation'
import { useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { COPY } from '@/lib/contract-copy'
import { use } from 'react'

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
  const [open, setOpen] = useState<number | null>(null)

  return (
    <article className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 pb-16">
      <h1 className="text-2xl font-semibold text-charcoal tracking-[-0.02em] mb-8 border-b border-gold/15 pb-5">
        {COPY.staticPages.faq.title}
      </h1>
      <div className="flex flex-col divide-y divide-gold/10">
        {COPY.staticPages.faq.items.map((item, i) => (
          <div key={i}>
            <button
              onClick={() => setOpen(open === i ? null : i)}
              aria-expanded={open === i}
              className="w-full flex items-center justify-between gap-4 py-4 text-right"
            >
              <span className="text-sm font-medium text-charcoal leading-snug">
                {item.q}
              </span>
              <ChevronDown
                size={16}
                aria-hidden="true"
                className={`text-gold shrink-0 transition-transform duration-200 ${open === i ? 'rotate-180' : ''}`}
              />
            </button>
            {open === i && (
              <p className="text-muted text-sm leading-relaxed pb-4 pr-1">
                {item.a}
              </p>
            )}
          </div>
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

// ── Route ────────────────────────────────────────────────────────────────────

export default function StaticPage({ params }: { params: Promise<{ policy: string }> }) {
  const { policy } = use(params)

  if (policy === 'faq')   return <FaqPage />
  if (policy === 'about') return <AboutPage />

  if (policy === 'terms')
    return <SectionedPage title={COPY.staticPages.terms.title}   sections={COPY.staticPages.terms.sections} />
  if (policy === 'returns')
    return <SectionedPage title={COPY.staticPages.returns.title} sections={COPY.staticPages.returns.sections} />
  if (policy === 'privacy')
    return <SectionedPage title={COPY.staticPages.privacy.title} sections={COPY.staticPages.privacy.sections} />

  notFound()
}

export function generateStaticParams() {
  return ['about', 'faq', 'returns', 'terms', 'privacy'].map(policy => ({ policy }))
}
