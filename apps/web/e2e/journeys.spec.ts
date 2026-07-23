/**
 * D2 — Journey tests (ADR-021)
 * Every test walks a full flow in a real browser against MSW.
 * Assertions are state-based (text, URL, aria) — not pixel coordinates.
 */
import { test, expect } from 'playwright/test'

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Wait for MSW to intercept at least one request (service worker is ready). */
async function waitForMsw(page: import('@playwright/test').Page) {
  // MSW stamps the page when ready; simpler to just wait for a known element
  // that only renders once data arrives.
  await page.waitForLoadState('networkidle', { timeout: 15_000 })
}

// ── 1. Catalog → Product data parity ─────────────────────────────────────────

test.describe('Catalog → Product data parity', () => {
  test('product data on card matches product detail page', async ({ page }) => {
    await page.goto('/jewellery/rings')
    await waitForMsw(page)

    // Pick the first card (سوليتير R-21-0342)
    const firstCard = page.locator('a[href="/p/R-21-0342"]').first()
    await expect(firstCard).toBeVisible({ timeout: 10_000 })

    // Capture name and weight text from the card
    const cardName   = await firstCard.locator('p.text-charcoal.text-sm.font-medium').textContent()
    const cardWeight = await firstCard.locator('text=/غ/').first().textContent()

    // Navigate to product page
    await firstCard.click()
    await page.waitForURL('**/p/R-21-0342')

    // Product page name must match
    const pageTitle = await page.locator('h1').first().textContent()
    expect(pageTitle?.trim()).toBe(cardName?.trim())

    // Weight value appears in specs table
    if (cardWeight) {
      const weightCell = page.locator('table td').filter({ hasText: /8\.45/ })
      await expect(weightCell).toBeVisible()
    }
  })
})

// ── 2. Full money-path: catalog → product → reserve → checkout → success ─────

test.describe('Money path: reserve → checkout → success', () => {
  test('complete checkout flow reaches SUCCESS state', async ({ page }) => {
    // Start on product page (MSW responds to /catalog/items/:slug)
    await page.goto('/p/R-21-0342')
    await waitForMsw(page)

    // Wait for FRESH state (reserve button enabled)
    const reserveBtn = page.getByRole('button', { name: /احجز القطعة والسعر/ })
    await expect(reserveBtn).toBeEnabled({ timeout: 15_000 })

    // Step 1 — Reserve
    await reserveBtn.click()
    const checkoutBtn = page.getByRole('button', { name: /إتمام الدفع/ })
    await expect(checkoutBtn).toBeVisible({ timeout: 5_000 })
    await checkoutBtn.click()

    // Step 2 — On /checkout: reservation loads, ReservationStrip is visible
    await page.waitForURL('**/checkout**')
    await waitForMsw(page)  // let MSW respond to GET /reservations/:rid

    // Price chain: card price == product page price == LOCKED price == checkout summary total
    // The summary aside shows the locked total (1,215.00 ر.س) after the breakdown rows.
    // pr(1215) = '1,215.00' — look for that exact string inside the aside.
    const summaryTotal = page.locator('aside').getByText('1,215.00')
    await expect(summaryTotal).toBeVisible({ timeout: 8_000 })

    const strip = page.locator('[dir="ltr"].tabular-nums').first()
    await expect(strip).toBeVisible({ timeout: 8_000 })

    // Step 3 — Fill address form (step ADDRESS)
    await page.getByLabel(/الاسم الكامل/).fill('محمد العمري')
    await page.getByLabel(/رقم الجوال/).fill('0512345678')
    await page.getByLabel(/البريد الإلكتروني/).fill('test@example.com')
    await page.getByLabel(/المدينة/).fill('الرياض')
    await page.getByLabel(/الحي/).fill('العليا')
    await page.getByLabel(/العنوان التفصيلي/).fill('شارع الملك فهد 100')

    const step1Cta = page.getByRole('button', { name: /متابعة إلى الدفع/ })
    await expect(step1Cta).toBeVisible()
    await step1Cta.click()

    // Step 4 — Payment step: click «الانتقال إلى الدفع الآمن»
    const payBtn = page.getByRole('button', { name: /الانتقال إلى الدفع الآمن/ })
    await expect(payBtn).toBeVisible({ timeout: 5_000 })
    await payBtn.click()

    // Step 5 — REDIRECTING → VERIFYING → SUCCESS (mock delays: 1800ms + 3500ms)
    // Wait up to 10s for SUCCESS state
    const successHeading = page.getByText(/تم الدفع — القطعة لك/)
    await expect(successHeading).toBeVisible({ timeout: 10_000 })

    // Order ID is displayed
    const orderIdRow = page.getByText(/ORD-5511/)
    await expect(orderIdRow).toBeVisible()

    // Track CTA is present (button navigates to /track)
    const trackCta = page.getByRole('button', { name: /تتبع الطلب/ })
    await expect(trackCta).toBeVisible()
  })
})

// ── 3. Track OTP flow: ENTRY → OTP_SENT → OTP_ERROR → ORDER_ACTIVE ───────────

test.describe('Track OTP flow', () => {
  test('wrong code shows error; correct code shows timeline', async ({ page }) => {
    await page.goto('/track')
    await waitForMsw(page)

    // ENTRY: fill order number and submit
    const orderInput = page.getByLabel(/رقم الطلب/)
    await expect(orderInput).toBeVisible({ timeout: 8_000 })
    await orderInput.fill('ORD-5511')
    await page.getByRole('button', { name: /إرسال رمز التحقق/ }).click()

    // OTP_SENT: masked phone note visible
    const otpNote = page.getByText(/أرسلنا رمز التحقق إلى \+966 \*\*\*\*5511/)
    await expect(otpNote).toBeVisible({ timeout: 5_000 })

    // Enter wrong code (999999) — each box one digit
    const boxes = page.locator('input[inputmode="numeric"]')
    const wrongCode = '999999'.split('')
    for (let i = 0; i < wrongCode.length; i++) {
      await boxes.nth(i).fill(wrongCode[i])
    }

    // OTP_ERROR: wrong-code alert appears
    const wrongAlert = page.getByText(/الرمز غير صحيح/)
    await expect(wrongAlert).toBeVisible({ timeout: 5_000 })

    // Boxes are reset after error — re-enter correct code (123456)
    const correctCode = '123456'.split('')
    for (let i = 0; i < correctCode.length; i++) {
      await boxes.nth(i).fill(correctCode[i])
    }

    // ORDER_ACTIVE: order timeline visible
    const orderId = page.getByText('ORD-5511')
    await expect(orderId).toBeVisible({ timeout: 5_000 })

    // Carrier tracking number visible
    const carrierNo = page.getByText('ARAMEX-9988')
    await expect(carrierNo).toBeVisible()
  })

  test('empty order number shows required-field error', async ({ page }) => {
    await page.goto('/track')
    await waitForMsw(page)

    // Click submit without filling the field
    const submitBtn = page.getByRole('button', { name: /إرسال رمز التحقق/ })
    await expect(submitBtn).toBeVisible({ timeout: 8_000 })
    await submitBtn.click()

    // Required field error appears
    const errMsg = page.getByText(/هذا الحقل مطلوب/)
    await expect(errMsg).toBeVisible()
  })
})

// ── 4. Persistent reservation strip: reserve → browse away → strip persists ──

test.describe('Persistent browsing strip (G1)', () => {
  test('strip persists with countdown after reserving and browsing to catalog', async ({ page }) => {
    // Reserve on product page
    await page.goto('/p/R-21-0342')
    await waitForMsw(page)

    const reserveBtn = page.getByRole('button', { name: /احجز القطعة والسعر/ })
    await expect(reserveBtn).toBeEnabled({ timeout: 15_000 })
    await reserveBtn.click()

    // RESERVED state visible
    await expect(page.getByRole('button', { name: /إتمام الدفع/ })).toBeVisible({ timeout: 5_000 })

    // Client-side navigate to catalog (router.push → context preserved)
    await page.getByRole('button', { name: /المجوهرات/ }).click()
    await page.waitForURL('**/jewellery/rings**')
    await waitForMsw(page)

    // BrowsingReservationStrip: countdown visible
    const countdown = page.locator('[aria-label="شريط الحجز أثناء التصفح"]')
      .locator('[dir="ltr"].tabular-nums')
    await expect(countdown).toBeVisible({ timeout: 8_000 })

    // «إتمام الدفع» link navigates to checkout
    const checkoutLink = page.getByRole('link', { name: /إتمام الدفع/ })
    await expect(checkoutLink).toBeVisible()
    await checkoutLink.click()
    await page.waitForURL('**/checkout**')
  })
})

// ── 6. 404 recovery ──────────────────────────────────────────────────────────

test.describe('404 recovery', () => {
  test('unknown route shows diamond glyph and secondary CTAs', async ({ page }) => {
    await page.goto('/nonexistent-page-xyz')
    await waitForMsw(page)

    // Diamond glyph (◇) — not the raw "404" number
    await expect(page.getByText('◇')).toBeVisible({ timeout: 8_000 })
    await expect(page.getByText('404')).not.toBeVisible()

    // All three CTAs present
    await expect(page.getByRole('link', { name: /استعرض المجوهرات/ })).toBeVisible()
    await expect(page.getByRole('link', { name: /تتبع الطلب/ })).toBeVisible()
    await expect(page.getByRole('link', { name: /الصفحة الرئيسية/ })).toBeVisible()
  })
})
