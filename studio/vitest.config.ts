import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  test: {
    clearMocks: true,
    css: true,
    environment: 'jsdom',
    environmentOptions: {
      jsdom: {
        pretendToBeVisual: true,
        url: 'http://127.0.0.1/',
      },
    },
    exclude: ['e2e/**', 'node_modules/**', 'dist/**'],
    include: ['src/web/**/*.test.{ts,tsx}'],
    restoreMocks: true,
    setupFiles: ['./src/test/setup.ts'],
    testTimeout: 5_000,
    unstubEnvs: true,
    unstubGlobals: true,
  },
})
