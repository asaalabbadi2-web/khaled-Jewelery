/**
 * D1 — Per-route visual baselines (ADR-021)
 * Captures one screenshot per route × key state.
 * Run with --update-snapshots to establish / refresh baselines.
 * CI compares against committed baseline PNGs in e2e/snapshots/.
 *
 * Routes covered (6 routes × key states):
 *   / (homepage)
 *   /jewellery/rings (catalog — no filters)
 *   /p/R-21-0342 (product — AVAILABLE state)
 *   /checkout (EXPIRED — stable state, no countdown)
 *   /track (ENTRY state)
 *   /terms (static page)
 */
import { test, expect } from 'playwright/test'

const VIEWPORT = { width: 1280, height: 800 }

// Disable animations so screenshots are stable
test.use({
  viewport:            VIEWPORT,
  reducedMotion:       'reduce',
  // Give MSW time to intercept the first fetch before snapshot
  actionTimeout:       15_000,
})

async function waitReady(page: import('@playwright/test').Page) {
  await page.waitForLoadState('networkidle', { timeout: 20_000 })
}

test('snapshot: homepage', async ({ page }) => {
  await page.goto('/')
  await waitReady(page)
  await expect(page).toHaveScreenshot('homepage.png', { maxDiffPixels: 200 })
})

test('snapshot: catalog (rings, no filter)', async ({ page }) => {
  await page.goto('/jewellery/rings')
  await waitReady(page)
  await expect(page).toHaveScreenshot('catalog-rings.png', { maxDiffPixels: 200 })
})

test('snapshot: product page (R-21-0342)', async ({ page }) => {
  await page.goto('/p/R-21-0342')
  await waitReady(page)
  // Mask the gold bar countdown to avoid noise from age ticking
  await expect(page).toHaveScreenshot('product-R-21-0342.png', {
    maxDiffPixels: 200,
    mask: [page.locator('[role="banner"]')],
  })
})

test('snapshot: checkout (EXPIRED state — stable, no countdown)', async ({ page }) => {
  // RSV-SNAP is pre-seeded in the MSW store with an epoch timestamp — always expired
  await page.goto('/checkout?rid=RSV-SNAP')
  await waitReady(page)
  await expect(page).toHaveScreenshot('checkout-expired.png', { maxDiffPixels: 200 })
})

test('snapshot: track (ENTRY state)', async ({ page }) => {
  await page.goto('/track')
  await waitReady(page)
  await expect(page).toHaveScreenshot('track-entry.png', { maxDiffPixels: 200 })
})

test('snapshot: terms (static page)', async ({ page }) => {
  await page.goto('/terms')
  await waitReady(page)
  await expect(page).toHaveScreenshot('terms.png', { maxDiffPixels: 200 })
})
