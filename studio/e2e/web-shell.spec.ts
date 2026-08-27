import { expect, test } from './fixtures'

test('serves and mounts the web shell without third-party requests', async ({ guardedPage }) => {
  await guardedPage.route('**/api/web/v1/demos', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ schemaVersion: '1.0.0', demos: [] }),
  }))
  const response = await guardedPage.goto('/', { waitUntil: 'networkidle' })

  expect(response?.ok()).toBe(true)
  await expect(guardedPage.locator('html')).toHaveAttribute('lang', 'en')
  await expect(guardedPage.locator('#root')).not.toBeEmpty()
  await expect(guardedPage.getByRole('heading', { name: /visual control surface/i })).toBeVisible()
  await expect(guardedPage.getByText('PUBLIC REPLAY NOT SUPPLIED')).toBeVisible()
  await expect(guardedPage.getByRole('link', { name: /recorded replay/i })).toHaveCount(0)
})

test('renders direct public routes and fails closed for private routes without Firebase', async ({ guardedPage }) => {
  await guardedPage.route('**/api/web/v1/demos', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ schemaVersion: '1.0.0', demos: [] }) }))
  await guardedPage.goto('/about')
  await expect(guardedPage.getByRole('heading', { name: 'A visual story for governed migration' })).toBeVisible()
  await expect(guardedPage.getByText('No creator or contributor information has been supplied.')).toBeVisible()

  await guardedPage.goto('/dashboard')
  await expect(guardedPage.getByRole('heading', { name: 'Authentication is not configured' })).toBeVisible()

  await guardedPage.goto('/route-that-does-not-exist')
  await expect(guardedPage.getByText('REQUESTED PATH: /route-that-does-not-exist')).toBeVisible()
})

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
