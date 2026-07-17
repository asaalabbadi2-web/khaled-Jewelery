import { test, expect } from 'playwright/test'

test.describe('Reserve → Checkout flow', () => {
  test('continuous countdown after navigating to checkout', async ({ page }) => {
    // 1. Load product page and wait for MSW to be ready
    await page.goto('/p/R-21-0342')

    // Wait for the reserve button to be enabled (FRESH state)
    const reserveBtn = page.getByRole('button', { name: /احجز|حجز/ })
    await expect(reserveBtn).toBeEnabled({ timeout: 10_000 })

    // 2. Reserve
    await reserveBtn.click()

    // Countdown becomes visible once RESERVED state kicks in
    const countdownEl = page.locator('[dir="ltr"].tabular-nums').first()
    await expect(countdownEl).toBeVisible({ timeout: 5_000 })

    // Capture the countdown value just before navigation
    const beforeText = await countdownEl.textContent()
    const beforeMs   = parseTime(beforeText ?? '')

    // 3. Click «إتمام الدفع»
    const checkoutBtn = page.getByRole('button', { name: /إتمام الدفع/ })
    await expect(checkoutBtn).toBeVisible()
    await checkoutBtn.click()

    // 4. Checkout page: ReservationStrip must be visible
    const strip = page.getByRole('region', { name: /الحجز|وقت|countdown/i })
      .or(page.locator('[aria-label]').filter({ hasText: /ر\.س|وقت/ }))

    // Simpler: just check the countdown text appears in the strip area
    const stripCountdown = page.locator('div.fixed.bg-charcoal [dir="ltr"]')
    await expect(stripCountdown).toBeVisible({ timeout: 5_000 })

    // 5. Countdown must be continuous — within 5s of where it was before navigation
    const afterText = await stripCountdown.textContent()
    const afterMs   = parseTime(afterText ?? '')

    // Both are derived from the same expiresAt timestamp → afterMs ≤ beforeMs
    // and the gap must be < 5s (navigation + render takes < 3s in practice)
    expect(afterMs).toBeLessThanOrEqual(beforeMs + 1_000)
    expect(beforeMs - afterMs).toBeLessThan(5_000)
  })
})

/** Parse "M:SS" or "MM:SS" countdown text → milliseconds */
function parseTime(text: string): number {
  const match = text.trim().match(/^(\d+):(\d{2})$/)
  if (!match) return 0
  return (parseInt(match[1], 10) * 60 + parseInt(match[2], 10)) * 1_000
}
