import { expect, test } from './fixtures'

test('serves and mounts the web shell without third-party requests', async ({ guardedPage }) => {
  const response = await guardedPage.goto('/', { waitUntil: 'networkidle' })

  expect(response?.ok()).toBe(true)
  await expect(guardedPage.locator('html')).toHaveAttribute('lang', 'en')
  await expect(guardedPage.locator('#root')).not.toBeEmpty()
})
