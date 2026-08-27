import { expect, test } from './fixtures'
import AxeBuilder from '@axe-core/playwright'
import type { Page } from '@playwright/test'

const emptyDemoList = { schemaVersion: '1.0.0', demos: [] }

async function serveEmptyDemoList(page: Page) {
  await page.route('**/api/web/v1/demos', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(emptyDemoList),
  }))
}

test('serves and mounts the web shell without third-party requests', async ({ guardedPage }) => {
	await serveEmptyDemoList(guardedPage)
  const response = await guardedPage.goto('/', { waitUntil: 'networkidle' })

  expect(response?.ok()).toBe(true)
  await expect(guardedPage.locator('html')).toHaveAttribute('lang', 'en')
  await expect(guardedPage.locator('#root')).not.toBeEmpty()
  await expect(guardedPage.getByRole('heading', { name: /visual control surface/i })).toBeVisible()
  await expect(guardedPage.getByText('PUBLIC REPLAY NOT SUPPLIED')).toBeVisible()
  await expect(guardedPage.getByRole('link', { name: /recorded replay/i })).toHaveCount(0)
})

test('renders direct public routes and fails closed for private routes without Firebase', async ({ guardedPage }) => {
	await serveEmptyDemoList(guardedPage)
  await guardedPage.goto('/about')
  await expect(guardedPage.getByRole('heading', { name: 'A visual story for governed migration' })).toBeVisible()
  await expect(guardedPage.getByText('No creator or contributor information has been supplied.')).toBeVisible()

  await guardedPage.goto('/dashboard')
  await expect(guardedPage.getByRole('heading', { name: 'Authentication is not configured' })).toBeVisible()

  await guardedPage.goto('/route-that-does-not-exist')
  await expect(guardedPage.getByText('REQUESTED PATH: /route-that-does-not-exist')).toBeVisible()
})

for (const scenario of [
  { name: 'desktop dark', width: 1440, height: 900, theme: 'dark', reducedMotion: 'no-preference' as const },
  { name: 'tablet light', width: 768, height: 1024, theme: 'light', reducedMotion: 'no-preference' as const },
  { name: 'mobile reduced motion', width: 390, height: 844, theme: 'dark', reducedMotion: 'reduce' as const },
]) {
  test(`landing is responsive and has no serious accessibility violations: ${scenario.name}`, async ({ guardedPage }) => {
    await guardedPage.setViewportSize({ width: scenario.width, height: scenario.height })
    await guardedPage.emulateMedia({ reducedMotion: scenario.reducedMotion })
    await guardedPage.addInitScript((theme) => window.localStorage.setItem('ztm-theme', theme), scenario.theme)
    await serveEmptyDemoList(guardedPage)
    await guardedPage.goto('/', { waitUntil: 'networkidle' })

    await expect(guardedPage.locator('html')).toHaveAttribute('data-theme', scenario.theme)
    await expect(guardedPage.getByRole('heading', { name: /visual control surface/i })).toBeVisible()
    const results = await new AxeBuilder({ page: guardedPage }).analyze()
    const serious = results.violations.filter((violation) => violation.impact === 'critical' || violation.impact === 'serious')
    expect(serious).toEqual([])
  })
}

test('advertises only a server-returned owner publication', async ({ guardedPage }) => {
  await guardedPage.route('**/api/web/v1/demos', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ schemaVersion: '1.0.0', demos: [{ schemaVersion: '1.0.0', demoId: 'demo_12345678', title: 'Owner approved synthetic run', sourceRunId: 'mig_123456789012', publishedAt: '2026-08-27T12:00:00.000Z', bundleDigest: `sha256:${'a'.repeat(64)}` }] }),
  }))
  await guardedPage.goto('/')
  const replay = guardedPage.getByRole('link', { name: 'Open exact recorded replay' })
  await expect(replay).toBeVisible()
  await expect(replay).toHaveAttribute('href', '/demo/demo_12345678')
})
