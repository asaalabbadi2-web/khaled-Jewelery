/**
 * FC-1 — Domain State Visibility gate.
 * Every (component, state) pair in STATE_STORY_REGISTRY must have a
 * corresponding named export in the story file.
 */
import { describe, it, expect } from 'vitest'

// Registry: [component, state, storyExportName]
// 34 entries covering GoldPriceStatus(3) + ItemAvailability(3) + PricingState(13)
// + OrderStatus(5) + ReservationStrip timer states(3) + SiteHeader nav(4) + SiteFooter(1) + OtpInput(1) + ProductCard skeleton(1)
const STATE_STORY_REGISTRY: Array<[string, string, string]> = [
  // GoldPriceStatus (3/3)
  ['GoldLiveBar', 'FRESH',  'Fresh'],
  ['GoldLiveBar', 'STALE',  'Stale'],
  ['GoldLiveBar', 'HALTED', 'Halted'],

  // ItemAvailability (3/3) + loading skeleton
  ['ProductCard', 'AVAILABLE', 'Available'],
  ['ProductCard', 'RESERVED',  'Reserved'],
  ['ProductCard', 'SOLD',      'Sold'],
  ['ProductCard', 'SKELETON',  'Skeleton'],

  // PricingState (13/13 — composite of ItemAvailability + ReservationStatus + PaymentStatus + GoldPriceStatus)
  ['PricingCard', 'DEFAULT',           'Default'],
  ['PricingCard', 'RESERVED',          'Reserved'],
  ['PricingCard', 'EXPIRED',           'Expired'],
  ['PricingCard', 'STALE',             'Stale'],
  ['PricingCard', 'HALTED',            'Halted'],
  ['PricingCard', 'RESERVED_BY_OTHER', 'ReservedByOther'],
  ['PricingCard', 'RACE_CONFLICT',     'RaceConflict'],
  ['PricingCard', 'SOLD',              'Sold'],
  ['PricingCard', 'PAYMENT_VERIFYING', 'PaymentVerifying'],
  ['PricingCard', 'LATE_PAYMENT',      'LatePayment'],
  ['PricingCard', 'REFUNDED',          'Refunded'],
  ['PricingCard', 'OFFLINE',           'Offline'],
  ['PricingCard', 'SKELETON',          'Skeleton'],

  // OrderStatus (5/6 — PAID maps to Active; OrderStatus.PAID triggers PREPARING which is Active)
  ['OrderTimeline', 'PREPARING',        'Active'],
  ['OrderTimeline', 'SHIPMENT_CREATED', 'ShipmentCreated'],
  ['OrderTimeline', 'SHIPPED',          'Shipped'],
  ['OrderTimeline', 'DELIVERED',        'Delivered'],
  ['OrderTimeline', 'CANCELLED',        'Cancelled'],

  // ReservationStrip timer states (maps to ReservationStatus.ACTIVE + CONFIRMED)
  ['ReservationStrip', 'ACTIVE',     'Normal'],
  ['ReservationStrip', 'URGENT',     'Urgent'],
  ['ReservationStrip', 'CONFIRMED',  'Frozen'],

  // SiteHeader navigation states (not domain-enum but observable UI states)
  ['SiteHeader', 'DEFAULT',        'Default'],
  ['SiteHeader', 'CATALOG_ACTIVE', 'CatalogActive'],
  ['SiteHeader', 'TRACK_ACTIVE',   'TrackActive'],
  ['SiteHeader', 'WITH_BANNER',    'WithBanner'],

  // SiteFooter + OtpInput (static render, one state each)
  ['SiteFooter', 'DEFAULT', 'Default'],
  ['OtpInput',   'DEFAULT', 'Default'],
]

describe('State coverage', () => {
  it('every registered state has a story', async () => {
    const [
      goldLiveBarStories,
      productCardStories,
      pricingCardStories,
      orderTimelineStories,
      reservationStripStories,
      siteHeaderStories,
      siteFooterStories,
      otpInputStories,
    ] = await Promise.all([
      import('../components/GoldLiveBar.stories'),
      import('../components/product/ProductCard.stories'),
      import('../components/pricing/PricingCard.stories'),
      import('../components/checkout/OrderTimeline.stories'),
      import('../components/checkout/ReservationStrip.stories'),
      import('../components/SiteHeader.stories'),
      import('../components/SiteFooter.stories'),
      import('../components/tracking/OtpInput.stories'),
    ])

    const moduleMap: Record<string, Record<string, unknown>> = {
      GoldLiveBar:      goldLiveBarStories,
      ProductCard:      productCardStories,
      PricingCard:      pricingCardStories,
      OrderTimeline:    orderTimelineStories,
      ReservationStrip: reservationStripStories,
      SiteHeader:       siteHeaderStories,
      SiteFooter:       siteFooterStories,
      OtpInput:         otpInputStories,
    }

    const missing: string[] = []

    for (const [component, state, exportName] of STATE_STORY_REGISTRY) {
      const storyModule = moduleMap[component]
      if (!storyModule || !(exportName in storyModule)) {
        missing.push(`${component}/${state} (export: ${exportName})`)
      }
    }

    expect(missing, `Missing stories:\n${missing.join('\n')}`).toHaveLength(0)
  })
})
