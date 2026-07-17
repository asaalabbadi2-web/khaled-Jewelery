import { notFound } from 'next/navigation'
import { COPY } from '@/lib/contract-copy'

const STATIC_PAGES: Record<string, { title: string; body: string }> = {
  about: {
    title: COPY.nav.about,
    body: 'معلومات عن متجرنا ستظهر هنا.',
  },
  faq: {
    title: COPY.footer.links.faq,
    body: 'الأسئلة الشائعة ستظهر هنا.',
  },
  returns: {
    title: COPY.footer.links.returns,
    body: 'سياسة الاسترجاع ستظهر هنا.',
  },
  terms: {
    title: COPY.footer.links.terms,
    body: 'الشروط والأحكام ستظهر هنا.',
  },
  privacy: {
    title: COPY.footer.links.privacy,
    body: 'سياسة الخصوصية ستظهر هنا.',
  },
}

export default function StaticPage({ params }: { params: { policy: string } }) {
  const page = STATIC_PAGES[params.policy]
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
