import { notFound } from 'next/navigation'
import { COPY } from '@/lib/contract-copy'

const STATIC_PAGES: Record<string, { title: string; body: string }> = {
  about: {
    title: COPY.nav.about,
    body: COPY.staticPages.about.body,
  },
  faq: {
    title: COPY.footer.links.faq,
    body: COPY.staticPages.faq.body,
  },
  returns: {
    title: COPY.footer.links.returns,
    body: COPY.staticPages.returns.body,
  },
  terms: {
    title: COPY.footer.links.terms,
    body: COPY.staticPages.terms.body,
  },
  privacy: {
    title: COPY.footer.links.privacy,
    body: COPY.staticPages.privacy.body,
  },
}

export default async function StaticPage({ params }: { params: Promise<{ policy: string }> }) {
  const { policy } = await params
  const page = STATIC_PAGES[policy]
  if (!page) notFound()

  return (
    <main className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 pb-16">
      <h1 className="text-2xl font-semibold text-charcoal tracking-[-0.02em] mb-6">
        {page.title}
      </h1>
      <p className="text-muted text-sm leading-relaxed">{page.body}</p>
    </main>
  )
}

export function generateStaticParams() {
  return Object.keys(STATIC_PAGES).map(policy => ({ policy }))
}
