'use client'

import { useRouter, usePathname } from 'next/navigation'
import { SiteHeader } from './SiteHeader'
import type { SiteHeaderProps } from './SiteHeader'

type ActivePage = NonNullable<SiteHeaderProps['active']>

const ROUTE_TO_ACTIVE: Record<string, ActivePage> = {
  '/jewellery': 'catalog',
  '/about':     'about',
  '/track':     'track',
}

export function SiteNavWrapper({ hasBanner }: { hasBanner?: boolean }) {
  const router   = useRouter()
  const pathname = usePathname()

  const active = Object.entries(ROUTE_TO_ACTIVE).find(
    ([route]) => pathname === route || pathname.startsWith(route + '/'),
  )?.[1]

  return (
    <SiteHeader
      hasBanner={hasBanner}
      active={active}
      onHome={()    => router.push('/')}
      onCatalog={() => router.push('/jewellery/rings')}
      onAbout={()   => router.push('/about')}
      onTrack={()   => router.push('/track')}
    />
  )
}
