import { expect, test as base } from '@playwright/test'
import type { Page } from '@playwright/test'

interface GuardOptions {
  allowedExternalOrigins: string[]
}

interface GuardFixtures {
  guardedPage: Page
}

export const test = base.extend<GuardOptions & GuardFixtures>({
  allowedExternalOrigins: [[], { option: true }],
  guardedPage: async ({ allowedExternalOrigins, baseURL, page }, runFixture) => {
    const appOrigin = baseURL ? new URL(baseURL).origin : undefined
    const allowedOrigins = new Set(allowedExternalOrigins)
    const runtimeErrors: string[] = []

    page.on('console', (message) => {
      if (message.type() === 'error') runtimeErrors.push(`console: ${message.text()}`)
    })
    page.on('pageerror', (error) => {
      runtimeErrors.push(`page: ${error.message}`)
    })

    await page.route('**/*', async (route) => {
      const requestUrl = new URL(route.request().url())
      const isNetworkRequest = requestUrl.protocol === 'http:' || requestUrl.protocol === 'https:'
      if (!isNetworkRequest || requestUrl.origin === appOrigin || allowedOrigins.has(requestUrl.origin)) {
        await route.continue()
        return
      }

      runtimeErrors.push(`blocked unexpected external request: ${requestUrl.origin}`)
      await route.abort('blockedbyclient')
    })

    await runFixture(page)

    expect(runtimeErrors, 'browser runtime and network guard').toEqual([])
  },
})

export { expect }
