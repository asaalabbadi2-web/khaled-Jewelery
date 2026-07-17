import { Suspense } from 'react'
import { CheckoutPageClient } from './CheckoutPageClient'

// Checkout has focused chrome (no live bar, no nav) — see CheckoutPageClient.
export default function CheckoutPage() {
  return (
    <Suspense>
      <CheckoutPageClient />
    </Suspense>
  )
}
