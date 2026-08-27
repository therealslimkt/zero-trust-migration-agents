import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { defineConfig, devices } from '@playwright/test'

const port = Number.parseInt(process.env.PLAYWRIGHT_PORT ?? '4173', 10)
const configuredBaseUrl = process.env.PLAYWRIGHT_BASE_URL?.trim()
const baseURL = configuredBaseUrl || `http://127.0.0.1:${port}`
const inCI = Boolean(process.env.CI)

export default defineConfig({
  testDir: './e2e',
  outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR || join(tmpdir(), 'ztm-playwright-results'),
  fullyParallel: true,
  forbidOnly: inCI,
  retries: inCI ? 2 : 0,
  workers: inCI ? 1 : undefined,
  reporter: inCI ? [['github'], ['line']] : 'list',
  timeout: 30_000,
  expect: {
    timeout: 5_000,
  },
  use: {
    baseURL,
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: configuredBaseUrl
    ? undefined
    : {
        command: `npm run dev -- --host 127.0.0.1 --port ${port}`,
        env: {
          MISSION_CONTROL_API_TOKEN:
            process.env.MISSION_CONTROL_API_TOKEN || '0000000000000000000000000000000000000000000000000000000000000000',
        },
        reuseExistingServer: !inCI,
        timeout: 120_000,
        url: baseURL,
      },
})
