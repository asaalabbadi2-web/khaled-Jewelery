import { COPY } from '@/lib/contract-copy'

export default function NotFound() {
  return (
    <main className="min-h-screen bg-ivory flex flex-col items-center justify-center px-4 text-center">
      <p className="text-charcoal text-5xl font-semibold tabular-nums mb-4" dir="ltr">404</p>
      <h1 className="text-charcoal text-xl font-semibold mb-3">{COPY.notFound.title}</h1>
      <p className="text-muted text-sm leading-relaxed max-w-sm mb-8">{COPY.notFound.sub}</p>
      <a
        href="/"
        className="inline-flex items-center justify-center bg-bronze text-surface py-3 px-6 rounded-sm text-sm font-semibold hover:bg-bronze-hover transition-colors"
      >
        {COPY.notFound.browseCta}
      </a>
    </main>
  )
}
