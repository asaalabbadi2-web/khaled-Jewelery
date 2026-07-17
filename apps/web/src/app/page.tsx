import { BRAND_NAME } from '@/lib/brand'
import { GoldLiveBar } from '@/components/GoldLiveBar'

export default function HomePage() {
  return (
    <main className="flex flex-col min-h-screen">
      <GoldLiveBar ageSeconds={30} />

      <div className="flex flex-1 flex-col items-center justify-center gap-6 px-4 py-16">
        <h1 className="text-4xl font-semibold text-charcoal tracking-tight text-center">
          {BRAND_NAME}
        </h1>
        <p className="text-charcoal/50 text-sm">قريباً</p>
      </div>
    </main>
  )
}
